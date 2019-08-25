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
                 tree,
                 tree_pool_id=-1):
        self.tree_pool_id = tree_pool_id
        self.tree = tree
        self.bg_adaptive_tree = None
        self.is_candidate = False
        self.warning_detector = ADWIN(args.warning_delta)
        self.drift_detector = ADWIN(args.drift_delta)
        self.predicted_labels = deque(maxlen=args.kappa_window)
        self.kappa = -sys.maxsize

    def update_kappa(self, actual_labels):
        if len(self.predicted_labels) < args.kappa_window:
            self.kappa = -sys.maxsize
        else:
            self.kappa = cohen_kappa_score(actual_labels, self.predicted_labels)
        return self.kappa

    def reset(self):
        self.bg_adaptive_tree = None
        self.is_candidate = False
        self.warning_detector.reset()
        self.drift_detector.reset()
        self.predicted_labels.clear()
        self.kappa = -sys.maxsize

def update_drift_detector(adaptive_tree, predicted_label, actual_label):
    if predicted_label == actual_label:
        adaptive_tree.warning_detector.add_element(0)
        adaptive_tree.drift_detector.add_element(0)
    else:
        adaptive_tree.warning_detector.add_element(1)
        adaptive_tree.drift_detector.add_element(1)

def predict(X, y, adaptive_trees, should_vote):
    predictions = []

    for i in range(0, len(X)):
        feature_row = X[i]
        label = y[i]

        votes = defaultdict(int)
        for adaptive_tree in adaptive_trees:
            predicted_label = adaptive_tree.tree.predict([feature_row])[0]

            adaptive_tree.predicted_labels.append(predicted_label) # for kappa calculation
            if should_vote:
                update_drift_detector(adaptive_tree, predicted_label, label)

            votes[predicted_label] += 1

            # background tree needs to predict for performance measurement
            if adaptive_tree.bg_adaptive_tree is not None:
                predict([feature_row], [label], [adaptive_tree.bg_adaptive_tree], False)

        if should_vote:
            predictions.append(max(votes, key=votes.get))

    return predictions

def partial_fit(X, y, adaptive_trees):
    for i in range(0, len(X)):
        for adaptive_tree in adaptive_trees:
            n = np.random.poisson(1)
            for j in range(0, n):
                adaptive_tree.tree.partial_fit([X[i]], [y[i]])
                if adaptive_tree.bg_adaptive_tree is not None:
                    adaptive_tree.bg_adaptive_tree.tree.partial_fit([X[i]], [y[i]])

def update_candidate_trees(candidate_trees,
                           tree_pool,
                           cur_state,
                           closest_state,
                           cur_tree_pool_size):
    if len(closest_state) == 0:
        return

    print(f"closest_state {closest_state}")
    print(f"cur_state {cur_state}")

    for i in range(0, cur_tree_pool_size):

        if cur_state[i] == '0' \
                and closest_state[i] == '1' \
                and not tree_pool[i].is_candidate:

            if len(candidate_trees) >= args.num_trees:
                worst_candidate = candidate_trees.pop(0)
                worst_candidate.reset()

            tree_pool[i].is_candidate = True
            candidate_trees.append(tree_pool[i])

    print("candidate_trees", [c.tree_pool_id for c in candidate_trees])

def adapt_state(drifted_tree_list,
                candidate_trees,
                tree_pool,
                cur_state,
                cur_tree_pool_size,
                adaptive_trees,
                drifted_tree_pos,
                actual_labels):

    if len(drifted_tree_list) == 0:
        return cur_tree_pool_size

    print("Drifts detected. Adapting states for", [t.tree_pool_id for t in drifted_tree_list])

    # sort candidates by kappa
    for candidate_tree in candidate_trees:
        candidate_tree.update_kappa(actual_labels)
    candidate_trees.sort(key=lambda c : c.kappa)

    for drifted_tree in drifted_tree_list:
        # TODO
        if cur_tree_pool_size >= args.tree_pool_size:
            print("early break")
            break

        drifted_tree.update_kappa(actual_labels)
        swap_tree = drifted_tree

        if len(candidate_trees) > 0 \
                and candidate_trees[-1].kappa - drifted_tree.kappa >= args.cd_kappa_threshold:
            # swap drifted tree with the candidate tree
            swap_tree = candidate_trees.pop()
            swap_tree.is_candidate = False

        swap_bg_tree = False
        if drifted_tree.bg_adaptive_tree is None:
            if swap_tree is drifted_tree:
                swap_tree = \
                    AdaptiveTree(tree=ARFHoeffdingTree(max_features=arf_max_features))
                swap_with_bg_tree = True

        else:
            window_size = len(drifted_tree.bg_adaptive_tree.predicted_labels)
            print(f"bg_tree window size: {window_size}")

            drifted_tree.bg_adaptive_tree.update_kappa(actual_labels)
            print(f"bg_tree kappa: {drifted_tree.bg_adaptive_tree.kappa} "
                  f"swap_tree.kappa: {swap_tree.kappa}")

            if drifted_tree.bg_adaptive_tree.kappa - swap_tree.kappa >= args.bg_kappa_threshold:

                # assign a new tree_pool_id for background tree
                # and add background tree to tree_pool
                swap_tree = drifted_tree.bg_adaptive_tree
                swap_bg_tree = True

        if swap_bg_tree:
            swap_tree.tree_pool_id = cur_tree_pool_size
            tree_pool[cur_tree_pool_size] = swap_tree
            cur_tree_pool_size += 1

        cur_state[drifted_tree.tree_pool_id] = '0'
        cur_state[swap_tree.tree_pool_id] = '1'

        # replace drifted tree with swap tree
        pos = drifted_tree_pos.pop()
        adaptive_trees[pos] = swap_tree
        drifted_tree.reset()

    return cur_tree_pool_size

def prequantial_evaluation(stream, adaptive_trees, lru_states, cur_state, tree_pool):
    correct = 0
    x_axis = []
    accuracy_list = []
    actual_labels = deque(maxlen=args.kappa_window) # a window of size arg.kappa_window

    current_state = []
    candidate_trees = []

    cur_tree_pool_size = args.num_trees

    with open('hyperplane.csv', 'w') as data_out, open('results.csv', 'w') as out:
        # pretrain
        X, y = stream.next_sample(args.wait_samples * 3)
        partial_fit(X, y, adaptive_trees)

        for row in X:
            features = ",".join(str(v) for v in row)
            data_out.write(f"{features},{str(y[0])}\n")

        for count in range(0, args.max_samples):
            X, y = stream.next_sample()
            actual_labels.append(y[0])

            # test
            prediction = predict(X, y, adaptive_trees, should_vote=True)[0]

            # test on candidate trees
            predict(X, y, candidate_trees, should_vote=False)

            if prediction == y[0]:
                correct += 1

            target_state = copy.deepcopy(cur_state)
            target_state_updated = False
            drifted_tree_list = []
            drifted_tree_pos = []

            for i in range(0, args.num_trees):

                tree = adaptive_trees[i]
                warning_detected_only = False
                if tree.warning_detector.detected_change():
                    warning_detected_only = True
                    tree.warning_detector.reset()

                    tree.bg_adaptive_tree = \
                        AdaptiveTree(tree=ARFHoeffdingTree(max_features=arf_max_features))

                if tree.drift_detector.detected_change():
                    warning_detected_only = False
                    tree.drift_detector.reset()
                    drifted_tree_list.append(tree)
                    drifted_tree_pos.append(i)

                    if args.disable_state_adaption:
                        if tree.bg_adaptive_tree is None:
                            tree = ARFHoeffdingTree(max_features=arf_max_features)
                        else:
                            tree.tree = tree.bg_adaptive_tree.tree
                            tree.bg_adaptive_tree = None

                if warning_detected_only:
                    target_state_updated = True
                    target_state[tree.tree_pool_id] = '2'

            if not args.disable_state_adaption:
                # if warnings are detected, find closest state and update candidate_trees list
                if target_state_updated:
                    closest_state = lru_states.get_closest_state(target_state)

                    update_candidate_trees(candidate_trees=candidate_trees,
                                           tree_pool=tree_pool,
                                           cur_state=cur_state,
                                           closest_state=closest_state,
                                           cur_tree_pool_size=cur_tree_pool_size)

                # if actual drifts are detected, swap trees and update cur_state
                cur_tree_pool_size = adapt_state(drifted_tree_list=drifted_tree_list,
                                                 candidate_trees=candidate_trees,
                                                 tree_pool=tree_pool,
                                                 cur_state=cur_state,
                                                 cur_tree_pool_size=cur_tree_pool_size,
                                                 adaptive_trees=adaptive_trees,
                                                 drifted_tree_pos=drifted_tree_pos,
                                                 actual_labels=actual_labels)

                lru_states.enqueue(cur_state)
                # print(f"Add state: {cur_state}")

            if (count % args.wait_samples == 0) and (count != 0):
                accuracy = correct / args.wait_samples
                print(f"{count},{accuracy}")

                x_axis.append(count)
                accuracy_list.append(accuracy)
                out.write(f"{count},{accuracy}\n")
                correct = 0

            # train
            partial_fit(X, y, adaptive_trees)

            features = ",".join(str(v) for v in X[0])
            data_out.write(f"{features},{str(y[0])}\n")

    return x_axis, accuracy_list

def evaluate():
    fig, ax = plt.subplots(2, 2, sharey=True, constrained_layout=True)

    stream = prepare_hyperplane_streams(noise_1=0.05, noise_2=0.1)
    stream.prepare_for_use()
    print(stream.get_data_info())

    adaptive_trees = [AdaptiveTree(tree_pool_id=i,
                                   tree=ARFHoeffdingTree(max_features=arf_max_features)
                      ) for i in range(0, args.num_trees)]

    cur_state = ['1' if i < args.num_trees else '0' for i in range(0, repo_size)]

    lru_states = LRU_state(capacity=repo_size, distance_threshold=100)
    lru_states.enqueue(cur_state)

    tree_pool = [None] * args.tree_pool_size
    for i in range(0, args.num_trees):
        tree_pool[i] = adaptive_trees[i]

    x_axis, accuracy_list = prequantial_evaluation(stream,
                                                   adaptive_trees,
                                                   lru_states,
                                                   cur_state,
                                                   tree_pool)

    ax[0, 0].plot(x_axis, accuracy_list)
    ax[0, 0].set_title("Accuracy")
    plt.xlabel("no. of instances")
    plt.show()

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument("-s", "--disable_state_adaption",
                        dest="disable_state_adaption", default=False, type=bool,
                        help="disable the state adaption algorithm")
    parser.add_argument("-t", "--tree",
                        dest="num_trees", default=1, type=int,
                        help="number of trees in the forest")
    parser.add_argument("-p", "--pool",
                        dest="tree_pool_size", default=180, type=int,
                        help="number of trees in the online tree repository")
    parser.add_argument("-w", "--warning",
                        dest="warning_delta", default=0.001, type=float,
                        help="delta value for drift warning detector")
    parser.add_argument("-d", "--drift",
                        dest="drift_delta", default=0.0001, type=float,
                        help="delta value for drift detector")
    parser.add_argument("--max_samples",
                        dest="max_samples", default=10000, type=int,
                        help="total number of samples")
    parser.add_argument("--wait_samples",
                        dest="wait_samples", default=100, type=int,
                        help="number of samples per evaluation")
    parser.add_argument("--kappa_window",
                        dest="kappa_window", default=25, type=int,
                        help="number of instances must be seen for calculating kappa")
    parser.add_argument("--random_state",
                        dest="random_state", default=0, type=int,
                        help="Seed used for adaptive hoeffding tree")
    parser.add_argument("--cd_kappa_threshold",
                        dest="cd_kappa_threshold", default=0.05, type=float,
                        help="Kappa value that the candidate tree needs to outperform both"
                             "background tree and foreground drifted tree")
    parser.add_argument("--bg_kappa_threshold",
                        dest="bg_kappa_threshold", default=0.05, type=float,
                        help="Kappa value that the background tree needs to outperform the "
                             "foreground drifted tree to prevent from false positive")

    args = parser.parse_args()

    print(f"num_trees: {args.num_trees}")
    print(f"warning_delta: {args.warning_delta}")
    print(f"drift_delta: {args.drift_delta}")
    print(f"max_samples: {args.max_samples}")
    print(f"wait_samples: {args.wait_samples}")
    print(f"kappa_window: {args.kappa_window}")
    print(f"random_state: {args.random_state}")

    num_classes = 2
    arf_max_features = int(math.log2(num_classes)) + 1
    repo_size = args.num_trees * 4

    np.random.seed(args.random_state)

    evaluate()