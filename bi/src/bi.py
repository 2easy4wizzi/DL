import re
# import pickle
# import json
import sys
import itertools
import zipfile
import os
import time
import math
import shutil
import pandas as pd
from collections import Counter
import numpy as np
import tensorflow as tf
import logging
import csv
from sklearn.model_selection import train_test_split
from collections import defaultdict

logging.getLogger().setLevel(logging.INFO)

LINE_FROM_CLASS = 5000
MINIMUM_ROW_LENGTH = 25
MAXIMUM_ROW_LENGTH = 150
BATCH_SIZE = 128
LSTM_HIDDEN_UNITS = 64
EPOCHS = 1
KEEP_PROB = 0.5

# GENERAL VARS
PRO_FLD = '../'
DATA_DIR = 'input/'
EMB_FILE = 'glove.6B.50d.txt'
EMB_DIM = 50
EMB_FILE_PATH = PRO_FLD + DATA_DIR + EMB_FILE
# DATA_FILE = '2way_rus_usa{}-{}.txt'.format(MINIMUM_ROW_LENGTH, MAXIMUM_ROW_LENGTH)
DATA_FILE = '2way_short{}-{}.txt'.format(MINIMUM_ROW_LENGTH, MAXIMUM_ROW_LENGTH)
DATA_FILE_PATH = PRO_FLD + DATA_DIR + DATA_FILE
COUNT_WORD = 20  # if a sentence has COUNT_WORD of the same word - it's a bad sentence (just a troll)

# existing FILES
TRA_FLD = 'trained_results_1533109035/'  # NOT used if USE_TMP_FOLDER is TRUE !!!
USE_TMP_FOLDER = True
PRINT_CLASSES_STATS_EACH_X_STEPS = 1  # prints dev stats each x steps


def clean_str(s):  # DATA
    strip_special_chars = re.compile("[^A-Za-z0-9 ,.]+")
    s = s.lower().replace("<br />", " ")
    return re.sub(strip_special_chars, "", s)


# for a sentence: get each token index in word_to_emb_mat_ind (if doesn't exist take last index)
def convert_data_to_indices_of_emb_mat(sentence):
    words_ind = np.zeros(MAXIMUM_ROW_LENGTH, dtype='int32')
    for i in range(len(sentence)):
        token = sentence[i]
        if i >= MAXIMUM_ROW_LENGTH:  # fail safe - shouldn't happen
            break
        # if word_to_emb_mat_ind.contains(token) save index. else save index==len(emb_mat) - for all unseen words
        words_ind[i] = gl_word_to_emb_mat_ind.get(token, len(gl_word_to_emb_mat_ind))
    return words_ind


def convert_data_to_word_indices(data_x):
    data_x_emb_indices = []
    for sentence in data_x:
        data_x_emb_indices.append(convert_data_to_indices_of_emb_mat(sentence))
    return np.matrix(data_x_emb_indices)


def load_data(data_full_path, shuffle=False):
    all_lines, data_x, labels_str, labels_int = [], [], [], []
    with open(data_full_path, 'r', encoding="utf8") as data_file:
        for line in data_file:
            all_lines.append(clean_str(line))

    print('Total data size is {}'.format(len(all_lines)))
    if shuffle:
        np.random.shuffle(all_lines)  # will affect the train test split

    for line in all_lines:
        split_line = line.split()
        label = split_line[0:1]
        sentence = split_line[1:]
        labels_str.append(label[0])
        data_x.append(sentence)

    l_unique_labels_list = np.unique(np.array(labels_str))
    l_unique_labels_dict = {}
    for i in range(len(l_unique_labels_list)):
        l_unique_labels_dict[l_unique_labels_list[i]] = i

    print('Our {} labels dictionary ={}'.format(len(l_unique_labels_dict), l_unique_labels_dict))

    for i in range(len(labels_str)):
        labels_int.append(l_unique_labels_dict[labels_str[i]])

    # split data to train - test
    split_train_test_percent = 0.9
    split_ind = math.floor(len(labels_int) * split_train_test_percent)

    l_test_x = data_x[split_ind:]
    l_test_y = labels_int[split_ind:]

    l_train_dev_x = data_x[:split_ind]
    l_train_dev_y = labels_int[:split_ind]

    # split train data to train - dev
    split_train_dev_percent = 0.9
    split_ind2 = math.floor(len(l_train_dev_y) * split_train_dev_percent)

    l_dev_x = l_train_dev_x[split_ind2:]
    l_dev_y = l_train_dev_y[split_ind2:]

    l_train_x = l_train_dev_x[:split_ind2]
    l_train_y = l_train_dev_y[:split_ind2]

    # convert words to their index in the embedding matrix
    l_train_x = convert_data_to_word_indices(l_train_x)
    l_dev_x = convert_data_to_word_indices(l_dev_x)
    l_test_x = convert_data_to_word_indices(l_test_x)

    print('x_train: {}, x_dev: {}, x_test: {}'.format(len(l_train_x), len(l_dev_x), len(l_test_x)))
    print('y_train: {}, y_dev: {}, y_test: {}'.format(len(l_train_y), len(l_dev_y), len(l_test_y)))

    return l_train_x, l_train_y, l_dev_x, l_dev_y, l_test_x, l_test_y, l_unique_labels_dict


# creates 2 objects
# l_word_to_emb_mat_ind: e.g. {'the' : 0, ',':1 ... }
#       the number of a key is the index in the l_emb_mat with leads to a EMB_DIM vector of floats
# l_emb_mat in the size len(l_word_to_emb_mat_ind) * EMB_DIM
def load_emb(emb_full_path):
    l_word_to_emb_mat_ind, l_emb_mat = {}, []
    with open(emb_full_path, 'r', encoding="utf8") as emb_file:
        for i, line in enumerate(emb_file.readlines()):
            split_line = line.split()
            l_word_to_emb_mat_ind[split_line[0]] = i
            embedding = np.array([float(val) for val in split_line[1:]], dtype='float32')
            l_emb_mat.append(embedding)

    # adding one more entry for all words that doesn't exist in the emb_full_path 
    l_emb_mat.append(np.zeros(EMB_DIM, dtype='float32'))
    print('Embedding tokens size={}'.format(len(l_emb_mat)))
    return l_word_to_emb_mat_ind, np.matrix(l_emb_mat, dtype='float32')


def get_bidirectional_rnn_model(l_emb_mat):
    tf.reset_default_graph()
    num_classes = len(gl_unique_labels_dict)
    input_data_x_batch = tf.placeholder(tf.int32, [BATCH_SIZE, MAXIMUM_ROW_LENGTH])
    input_labels_batch = tf.placeholder(tf.float32, [BATCH_SIZE, num_classes])
    keep_prob_pl = tf.placeholder(tf.float32)
    print("input_data_x_batch shape: {}".format(input_data_x_batch.get_shape()))
    print("input_labels_batch shape: {}".format(input_labels_batch.get_shape()))

    data = tf.nn.embedding_lookup(l_emb_mat, input_data_x_batch)

    lstm_fw_cell = tf.nn.rnn_cell.BasicLSTMCell(LSTM_HIDDEN_UNITS)
    print("lstm_fw_cell units: {}".format(LSTM_HIDDEN_UNITS))
    lstm_fw_cell = tf.contrib.rnn.DropoutWrapper(cell=lstm_fw_cell, output_keep_prob=keep_prob_pl, dtype=tf.float32)
    lstm_bw_cell = tf.contrib.rnn.BasicLSTMCell(LSTM_HIDDEN_UNITS)
    print("lstm_bw_cell units: {}".format(LSTM_HIDDEN_UNITS))
    lstm_bw_cell = tf.contrib.rnn.DropoutWrapper(cell=lstm_bw_cell, output_keep_prob=keep_prob_pl, dtype=tf.float32)
    outputs_as_vecs, _ = tf.nn.bidirectional_dynamic_rnn(lstm_fw_cell, lstm_bw_cell, data, dtype=tf.float32)

    outputs_as_vecs = tf.concat(outputs_as_vecs, 2)
    outputs_as_vecs = tf.transpose(outputs_as_vecs, [1, 0, 2])

    weight = tf.Variable(tf.truncated_normal([2 * LSTM_HIDDEN_UNITS, num_classes]))
    bias = tf.Variable(tf.constant(0.1, shape=[num_classes]))

    outputs_as_value = tf.gather(outputs_as_vecs, int(outputs_as_vecs.get_shape()[0]) - 1)
    prediction = (tf.matmul(outputs_as_value, weight) + bias)

    correct_pred = tf.equal(tf.argmax(prediction, 1), tf.argmax(input_labels_batch, 1))
    acc = tf.reduce_mean(tf.cast(correct_pred, tf.float32))

    l_loss = tf.reduce_mean(tf.nn.softmax_cross_entropy_with_logits_v2(logits=prediction, labels=input_labels_batch))
    l_optimizer = tf.train.AdamOptimizer().minimize(l_loss)

    return input_data_x_batch, input_labels_batch, keep_prob_pl, l_optimizer, l_loss, acc


def convert_to_array(label_value):
    label_zero_one_vec = [0] * len(gl_unique_labels_dict)
    label_zero_one_vec[label_value - 1] = 1
    return label_zero_one_vec


def get_batch_sequential(data_x, data_y, batch_num, batch_size):
    batch = data_x[batch_num * batch_size:(batch_num + 1) * batch_size]
    labels = [convert_to_array(label) for label in data_y[batch_num * batch_size:(batch_num + 1) * batch_size]]

    return batch, labels


def train(l_train_x, l_train_y):
    session_conf = tf.ConfigProto(allow_soft_placement=True, log_device_placement=False)
    sess = tf.Session(config=session_conf)
    with sess.as_default():
        sess.run(tf.global_variables_initializer())
        for i in range(EPOCHS):
            print("\nEpoch: {0}/{1}\n".format((i + 1), EPOCHS))
            batches_num = int(math.ceil(len(train_x) / BATCH_SIZE))
            for s in range(batches_num):
                batch_xs, batch_ys = get_batch_sequential(l_train_x, l_train_y, s, BATCH_SIZE)
                if len(batch_ys) != BATCH_SIZE:
                    continue

                _, batch_loss, batch_acc = sess.run([optimizer, loss, accuracy],
                                                    feed_dict={input_data: batch_xs, input_labels: batch_ys,
                                                               keep_prob: KEEP_PROB})

                # original: if s % 10
                # if s % _STEPS_PRINT == 0:
                msg = "STEP {}/{}: batch_acc = {:.4f}% , batch loss = {:.4f}"
                print(msg.format(s, batches_num-1, batch_acc*100, batch_loss))

                # current_error += 1 - batch_acc

            # print("loss avg for epoch {} is {}".format(epoch, current_loss / bacthes_num))
            # train_error_list.append(current_error / bacthes_num)
            # test_and_save(epoch)
    return


def test():
    return


def args_print(stage, duration=0):
    print("{} ----------------------".format(stage))
    hours, rem = divmod(duration, 3600)
    minutes, seconds = divmod(rem, 60)
    print("Time(HH:MM:SS): {:0>2}:{:0>2}:{:0>2}".format(int(hours), int(minutes), int(seconds)))
    return


if __name__ == '__main__':
    print("Entering function __main__")
    total_start_time = time.time()
    global gl_word_to_emb_mat_ind, gl_unique_labels_dict
    gl_word_to_emb_mat_ind, emb_mat = load_emb(EMB_FILE_PATH)
    train_x, train_y, dev_x, dev_y, test_x, test_y, gl_unique_labels_dict = load_data(DATA_FILE_PATH)
    input_data, input_labels, keep_prob, optimizer, loss, accuracy = get_bidirectional_rnn_model(emb_mat)
    train(train_x, train_y)
    # test()
    dur = time.time() - total_start_time
    args_print('End summary', int(dur))
    print("Leaving function __main__")
