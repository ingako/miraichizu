#!/usr/bin/env python3

import copy
import sys
import math
import argparse
import numpy as np
from collections import defaultdict, deque

from stream_generators import *
from LRU_state import *

from sklearn.metrics import cohen_kappa_score

from arf_hoeffding_tree import ARFHoeffdingTree
from skmultiflow.drift_detection.adwin import ADWIN

import matplotlib
import matplotlib.pyplot as plt
matplotlib.rcParams["backend"] = "Qt4Agg"
plt.rcParams["figure.figsize"] = (20, 10)

class AdaptiveTree(object):
    def __init__(self,
                 tree_pool_id,
                 fg_tree):
        self.tree_pool_id = tree_pool_id
        self.fg_tree = fg_tree
        self.bg_tree = None
        self.is_candidate = False
        self.warning_detector = ADWIN(args.warning_delta)
        self.drift_detector = ADWIN(args.drift_delta)
        self.kappa = -sys.maxsize

    def reset(self):
        self.bg_tree = None
        self.is_candidate = False
        self.warning_detector.reset()
        self.drift_detector.reset()
        self.kappa = -sys.maxsize

def update_drift_detector(adaptive_tree, predicted_label, actual_label):
    if predicted_label == actual_label:
        adaptive_tree.warning_detector.add_element(0)
        adaptive_tree.drift_detector.add_element(0)
    else:
        adaptive_tree.warning_detector.add_element(1)
        adaptive_tree.drift_detector.add_element(1)

def predict(X, y, trees, should_vote):
    predictions = []

    for i in range(0, len(X)):
        feature_row = X[i]
        label = y[i]

        votes = defaultdict(int)
        for tree in trees:
            predicted_label = tree.fg_tree.predict([feature_row])[0]

            # tree.predicted_labels.append(predicted_label) # for kappa calculation
            if should_vote:
                update_drift_detector(tree, predicted_label, label)

            votes[predicted_label] += 1

        if should_vote:
            predictions.append(max(votes, key=votes.get))

    return predictions

def partial_fit(X, y, trees):
    for i in range(0, len(X)):
        for tree in trees:
            n = np.random.poisson(1)
            for j in range(0, n):
                tree.fg_tree.partial_fit([X[i]], [y[i]])
                if tree.bg_tree is not None:
                    tree.bg_tree.partial_fit([X[i]], [y[i]])

def prequential_evaluation(stream, adaptive_trees):
    correct = 0
    x_axis = []
    accuracy_list = []

    sample_counter = 0
    window_accuracy = 0.0

    with open('results_arf.csv', 'w') as out:
        for count in range(0, args.max_samples):
            X, y = stream.next_sample(count)

            # test
            prediction = predict(X, y, adaptive_trees, should_vote=True)[0]

            if prediction == y[0]:
                correct += 1

            drifted_tree_list = []

            for tree in adaptive_trees:

                if tree.warning_detector.detected_change():
                    tree.warning_detector.reset()
                    tree.bg_tree = ARFHoeffdingTree(max_features=arf_max_features)

                if tree.drift_detector.detected_change():
                    tree.drift_detector.reset()
                    drifted_tree_list.append(tree)

                    if tree.bg_tree is None:
                        tree.fg_tree = ARFHoeffdingTree(max_features=arf_max_features)
                    else:
                        tree.fg_tree = tree.bg_tree
                    tree.reset()

            if (count % args.wait_samples == 0) and (count != 0):
                accuracy = correct / args.wait_samples
                correct = 0

                window_accuracy = (window_accuracy * sample_counter + accuracy) \
                    / (sample_counter + 1)
                sample_counter += args.wait_samples

                if sample_counter == args.sample_freq:
                    x_axis.append(count)
                    accuracy_list.append(window_accuracy)

                    print(f"{count},{window_accuracy}")
                    out.write(f"{count},{window_accuracy}\n")

                    sample_counter = 0
                    window_accuracy = 0.0

            # train
            partial_fit(X, y, adaptive_trees)

            # features = ",".join(str(v) for v in X[0])
            # data_out.write(f"{features},{str(y[0])}\n")

    return x_axis, accuracy_list

def evaluate():
    fig, ax = plt.subplots(2, 2, sharey=True, constrained_layout=True)

    # prepare data
    stream = prepare_data()
    print(stream.get_data_info())

    adaptive_trees = [AdaptiveTree(tree_pool_id=i,
                                   fg_tree=ARFHoeffdingTree(max_features=arf_max_features)
                      ) for i in range(0, args.num_trees)]

    x_axis, accuracy_list = prequential_evaluation(stream,
                                                   adaptive_trees)

    ax[0, 0].plot(x_axis, accuracy_list)
    ax[0, 0].set_title("Accuracy")
    plt.xlabel("no. of instances")
    plt.show()

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument("-t", "--tree",
                        dest="num_trees", default=60, type=int,
                        help="number of trees in the forest")
    parser.add_argument("-w", "--warning",
                        dest="warning_delta", default=0.0001, type=float,
                        help="delta value for drift warning detector")
    parser.add_argument("-d", "--drift",
                        dest="drift_delta", default=0.00001, type=float,
                        help="delta value for drift detector")
    parser.add_argument("--max_samples",
                        dest="max_samples", default=100000, type=int,
                        help="total number of samples")
    parser.add_argument("--wait_samples",
                        dest="wait_samples", default=100, type=int,
                        help="number of samples per evaluation")
    parser.add_argument("--sample_freq",
                        dest="sample_freq", default=1000, type=int,
                        help="log interval for performance")
    parser.add_argument("--random_state",
                        dest="random_state", default=0, type=int,
                        help="Seed used for adaptive hoeffding tree")
    args = parser.parse_args()

    print(f"num_trees: {args.num_trees}")
    print(f"warning_delta: {args.warning_delta}")
    print(f"drift_delta: {args.drift_delta}")
    print(f"max_samples: {args.max_samples}")
    print(f"wait_samples: {args.wait_samples}")

    num_labels = 2
    num_features = 10
    arf_max_features = int(math.log2(num_features)) + 1
    np.random.seed(args.random_state)

    evaluate()