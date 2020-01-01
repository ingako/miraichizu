#include "pearl.h"

pearl::pearl(int num_trees,
             int repo_size,
             int edit_distance_threshold,
             int kappa_window_size,
             int lossy_window_size,
             int reuse_window_size,
             int arf_max_features,
             double bg_kappa_threshold,
             double cd_kappa_threshold,
             double reuse_rate_upper_bound,
             double warning_delta,
             double drift_delta,
             bool enable_state_adaption) :
    num_trees(num_trees),
    repo_size(repo_size),
    edit_distance_threshold(edit_distance_threshold),
    kappa_window_size(kappa_window_size),
    lossy_window_size(lossy_window_size),
    reuse_window_size(reuse_window_size),
    arf_max_features(arf_max_features),
    bg_kappa_threshold(bg_kappa_threshold),
    cd_kappa_threshold(cd_kappa_threshold),
    reuse_rate_upper_bound(reuse_rate_upper_bound),
    warning_delta(warning_delta),
    drift_delta(drift_delta),
    enable_state_adaption(enable_state_adaption) {

    for (int i = 0; i < num_trees; i++) {
        unique_ptr<adaptive_tree> tree = make_adaptive_tree(i);
        adaptive_trees.push_back(move(tree));
    }
}

unique_ptr<pearl::adaptive_tree> pearl::make_adaptive_tree(int tree_pool_id) {
    return make_unique<adaptive_tree>(tree_pool_id,
                                      kappa_window_size,
                                      warning_delta,
                                      drift_delta);
}

bool pearl::init_data_source(const string& filename) {

    LOG("Initializing data source...");

    reader = new ArffReader();

    if (!reader->setFile(filename)) {
        LOG("Failed to open file: ");
        exit(1);
    }

    return true;
}

bool pearl::process() {
    int predicted_label;
    int actual_label = instance->getLabel();

    for (int i = 0; i < num_trees; i++) {
        predicted_label = predict(*instance);

        int num_classes = instance->getNumberClasses();

        int error_count = (int)(actual_label != predicted_label);

        // detect warning
        if (detect_change(error_count, adaptive_trees[i]->warning_detector)) {
            adaptive_trees[i]->bg_adaptive_tree = make_adaptive_tree(-1);
            adaptive_trees[i]->warning_detector->resetChange();
        }

        // detect drift
        if (detect_change(error_count, adaptive_trees[i]->drift_detector)) {
            adaptive_trees[i] = move(adaptive_trees[i]->bg_adaptive_tree);
            adaptive_trees[i]->drift_detector->resetChange();
        }

        adaptive_trees[i]->train(*instance);
    }

    return predicted_label == actual_label;
}

int pearl::predict(Instance& instance) {
    double numberClasses = instance.getNumberClasses();
    double* classPredictions = adaptive_trees[0]->tree->getPrediction(instance);
    int result = 0;
    double max = classPredictions[0];

    // Find class label with the highest probability
    for (int i = 1; i < numberClasses; i++) {
        if (max < classPredictions[i]) {
            max = classPredictions[i];
            result = i;
        }
    }

    return result;
}

bool pearl::detect_change(int error_count,
                          unique_ptr<HT::ADWIN>& detector) {

    double old_error = detector->getEstimation();
    bool error_change = detector->setInput(error_count);

    if (!error_change) {
       return false;
    }

    if (old_error > detector->getEstimation()) {
        // error is decreasing
        return false;
    }

    return true;
}


bool pearl::get_next_instance() {
    if (!reader->hasNextInstance()) {
        return false;
    }

    instance = reader->nextInstance();
    return true;
}

void pearl::set_num_trees(int num_trees_) {
    num_trees = num_trees_;
}

int pearl::get_num_trees() const {
    return num_trees;
}

// class adaptive_tree
pearl::adaptive_tree::adaptive_tree(int tree_pool_id,
                                    int kappa_window_size,
                                    double warning_delta,
                                    double drift_delta) :
        tree_pool_id(tree_pool_id),
        kappa_window_size(kappa_window_size),
        warning_delta(warning_delta),
        drift_delta(drift_delta) {

    tree = make_unique<HT::HoeffdingTree>();
    warning_detector = make_unique<HT::ADWIN>(warning_delta);
    drift_detector = make_unique<HT::ADWIN>(drift_delta);
}

void pearl::adaptive_tree::train(Instance& instance) {
    tree->train(instance);

    if (bg_adaptive_tree) {
        bg_adaptive_tree->train(instance);
    }
}

void pearl::adaptive_tree::update_kappa(int actual_labels) {

}

void pearl::adaptive_tree::reset() {

}
