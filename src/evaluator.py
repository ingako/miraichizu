import copy
from collections import deque
import time

import numpy as np
from sklearn.metrics import cohen_kappa_score

import sys
path = r'../'
if path not in sys.path:
    sys.path.append(path)
from build.pearl import adaptive_random_forest, pearl

class Evaluator:

    @staticmethod
    def prequential_evaluation(classifier,
                               stream,
                               max_samples,
                               sample_freq,
                               metrics_logger):
        correct = 0
        window_actual_labels = []
        window_predicted_labels = []

        metrics_logger.info("count,accuracy,kappa,memory,time")
        start_time = time.process_time()

        for count in range(0, max_samples):
            X, y = stream.next_sample()

            # test
            prediction = classifier.predict(X, y)[0]

            window_actual_labels.append(y[0])
            window_predicted_labels.append(prediction)
            if prediction == y[0]:
                correct += 1

            classifier.handle_drift(count)

            if count % sample_freq == 0 and count != 0:

                accuracy = correct / sample_freq
                kappa = cohen_kappa_score(window_actual_labels, window_predicted_labels)
                memory_usage = classifier.get_size()
                # elapsed_time = time.process_time() - start_time
                elapsed_time = 0

                metrics_logger.info(f"{count},{accuracy},{kappa}" \
                                    f"{memory_usage},{str(elapsed_time)}")

                correct = 0
                window_actual_labels = []
                window_predicted_labels = []

            # train
            classifier.partial_fit(X, y)

        print(f"length of candidate_trees: {len(classifier.candidate_trees)}")


    @staticmethod
    def prequential_evaluation_cpp(classifier,
                                   stream,
                                   max_samples,
                                   sample_freq,
                                   metrics_logger):
        correct = 0
        window_actual_labels = []
        window_predicted_labels = []
        if isinstance(classifier, pearl):
            print("is an instance of pearl, turn on log_size")

        log_size = isinstance(classifier, pearl)

        metrics_logger.info("count,accuracy,kappa,candidate_tree_size,tree_pool_size,time")
        start_time = time.process_time()

        classifier.init_data_source(stream);

        for count in range(0, max_samples):
            if not classifier.get_next_instance():
                break

            # test
            prediction = classifier.predict()

            actual_label = classifier.get_cur_instance_label()
            if prediction == actual_label:
                correct += 1

            window_actual_labels.append(actual_label)
            window_predicted_labels.append(prediction)

            if count % sample_freq == 0 and count != 0:
                accuracy = correct / sample_freq
                kappa = cohen_kappa_score(window_actual_labels, window_predicted_labels)
                elapsed_time = time.process_time() - start_time

                candidate_tree_size = 0
                tree_pool_size = 60
                if log_size:
                    candidate_tree_size = classifier.get_candidate_tree_group_size()
                    tree_pool_size = classifier.get_tree_pool_size()

                metrics_logger.info(f"{count},{accuracy},{kappa}," \
                                    f"{candidate_tree_size}," \
                                    f"{tree_pool_size}," \
                                    f"{str(elapsed_time)}")

                correct = 0
                window_actual_labels = []
                window_predicted_labels = []

            # train
            classifier.train()

            classifier.delete_cur_instance()
