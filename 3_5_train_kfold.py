import os
import sys
import lightgbm as lgb
import numpy as np
import pandas as pd
import argparse
from sklearn.model_selection import StratifiedKFold

from config import Config
from utils import (get_train_and_test_data, process_feature, save_model,
                   evaluate)
if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--pseudo',
                        action='store_true',
                        help='if use pseudo label data')

    args = parser.parse_args()
    config = Config(use_pseudo=args.pseudo)
    train_data, test_data = get_train_and_test_data(config)
    rt = test_data.copy()

    train_x = train_data.drop(config.drop_list, axis=1)  # 训练集输入
    train_y = train_data['label']  # 训练集标签

    test_x = test_data.drop(config.drop_list, axis=1)  # 测试集输入

    train_x, test_x = process_feature(train_x, test_x, config)
    train_x.to_csv("./data/train_processed.csv", index=False)
    train_y.to_csv("./data/train_label.csv", index=False)
    test_x.to_csv("./data/test_processed.csv", index=False)
    config.logger.info(train_y.value_counts())
    config.logger.info(f"Features: {train_x.columns.values}")
    config.logger.info(
        f"Train: {train_x.shape} {train_y.shape} Test: {test_x.shape}")

    # 十折交叉验证
    folds = StratifiedKFold(n_splits=config.num_fold,
                            shuffle=True,
                            random_state=3123)
    predictions = np.zeros(len(test_data))
    fbeta_score = 0.0
    p_score = r_score = f1_score = 0.0
    test_predictions = []
    for fold_, (trn_idx, val_idx) in enumerate(folds.split(train_x, train_y)):
        config.logger.info("fold n°{}".format(fold_ + 1))
        trn_data = lgb.Dataset(train_x.iloc[trn_idx], train_y[trn_idx])
        val_data = lgb.Dataset(train_x.iloc[val_idx],
                               train_y[val_idx],
                               free_raw_data=False)
        clf = lgb.train(config.lgb_params,
                        trn_data,
                        config.lgb_num_round,
                        valid_sets=[trn_data, val_data],
                        valid_names=["train", "dev"],
                        verbose_eval=1000,
                        early_stopping_rounds=1000)
        probs = clf.predict(test_x, num_iteration=clf.best_iteration)
        if config.use_vote:
            vote_predictions = (probs >= config.test_threshold).astype('int')
            test_predictions.append(vote_predictions)
        else:
            predictions += probs / folds.n_splits
        save_model(config, clf, config.lgb_save_path + str(fold_))
        fbeta, p, r, f1 = evaluate(config, clf, val_data, "dev")
        fbeta_score += fbeta / folds.n_splits
        p_score += p / folds.n_splits
        r_score += r / folds.n_splits
        f1_score += f1 / folds.n_splits
    config.logger.info(
        f"Current fbeta: {fbeta_score:.4f} p: {p_score:.4f} r: {r_score:.4f} f1: {f1_score:.4f}"
    )

    if config.use_vote:
        test_predictions = pd.DataFrame(test_predictions)
        vote_results = []
        for i in range(test_predictions.shape[1]):
            vote_result = test_predictions.iloc[:, i].value_counts().index[0]
            vote_results.append(vote_result)
        rt['label'] = vote_results
    else:
        rt['label'] = (predictions >= config.test_threshold).astype('int')
    label_count = rt["label"].value_counts()
    config.logger.info(
        pd.concat([label_count, label_count / label_count.sum()], axis=1))
    # rt.to_csv(config.result_path.replace('results', f'results_kfold_{fbeta_score:.4f}'),
    #           columns=['request_id', 'label'],
    #           index=False,
    #           sep=',')
    rt.to_csv(config.result_path.replace('results',
                                         f'results_kfold_{fbeta_score:.4f}'),
              columns=['id', 'label'],
              index=False,
              sep=',')

    os.system(f"cp saved/lgb.bin* {config.cur_dir}")
    os.system(f"mv {config.cur_dir} {config.cur_dir}_{fbeta_score:.4f}")
