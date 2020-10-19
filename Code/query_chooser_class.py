import csv
import datetime
import os
import random
import time
from itertools import combinations
from random import choice, sample

import numpy as np
import tensorflow as tf
from scipy.special import comb

from planner import BanditsModel, GridworldModel, NoPlanningModel


def random_combination(iterable, r):
    """Random selection from itertools.combinations(iterable, r)"""
    pool = tuple(iterable)
    n = len(pool)
    indices = sorted(sample(range(n), r))
    return tuple(pool[i] for i in indices)


def time_function(function, input):
    "Calls function and returns time it took"
    start = time.clock()
    function(input)
    deltat = time.clock() - start
    return deltat


class Query_Chooser(object):
    def __init__(self, num_queries_max, args, cost_of_asking=0, t_0=None):
        self.cost_of_asking = cost_of_asking
        self.num_queries_max = num_queries_max
        self.args = args  # all args
        self.t_0 = t_0
        self.model_cache = {}

        config = tf.ConfigProto()
        config.gpu_options.allow_growth = True
        self.sess = tf.Session(config=config)

    def cache_feature_expectations(self, reward_space=None):
        """Computes feature expectations for each proxy using TF and stores them in
        inference.feature_expectations_matrix."""
        use_proxy_space = (reward_space is None)
        if use_proxy_space:
            reward_space = self.inference.reward_space_proxy

        proxy_list = [list(reward) for reward in reward_space]
        print('building graph. Total experiment time: {t}'.format(t=time.clock() - self.t_0))
        # TODO: This will build a separate model for every reward space size after eliminating duplicates
        model = self.get_model(len(proxy_list), 'entropy', cache=(not use_proxy_space))
        model.initialize(self.sess)

        desired_outputs = ['feature_exps']
        mdp = self.inference.mdp
        print('Computing model outputs. Total experiment time: {t}'.format(t=time.clock() - self.t_0))
        [feature_exp_matrix] = model.compute(
            desired_outputs, self.sess, mdp, proxy_list)
        print('Done computing model outputs. Total experiment time: {t}'.format(t=time.clock() - self.t_0))

        if use_proxy_space:
            self.inference.feature_exp_matrix = feature_exp_matrix
        return feature_exp_matrix

    # @profile
    def find_query(self, query_size, chooser, true_reward):
        """Calls query chooser specified by chooser (string)."""
        # if chooser == 'maxmin':
        #     return self.find_query_feature_diff(query_size)
        measure = self.args.objective
        if chooser == 'exhaustive':
            return self.find_discrete_query(query_size, measure, true_reward, growth_rate=query_size,
                                            exhaustive_query=True)
        # elif chooser == 'greedy_regret':
        #     return self.find_best_query_greedy(query_size, true_reward=true_reward)
        elif chooser == 'random':
            return self.find_discrete_query(query_size, measure, true_reward, random_query=True)
        elif chooser == 'full':
            return self.find_discrete_query(query_size, measure, true_reward, full_query=True)
        # elif chooser == 'greedy_exp_reward':
        #     return self.find_best_query_greedy(query_size, total_reward=True, true_reward=true_reward)
        elif chooser == 'greedy_discrete':
            return self.find_discrete_query(query_size, measure, true_reward, growth_rate=1)
        elif chooser == 'incremental_optimize':
            return self.find_discrete_query_with_optimization(
                query_size, measure, true_reward, growth_rate=1)
        elif chooser == 'joint_optimize':
            return self.find_discrete_query_with_optimization(
                query_size, measure, true_reward, growth_rate=query_size)
        elif chooser == 'feature_entropy':
            self.search = False
            self.init_none = False
            self.no_optimize = False
            return self.find_feature_query_greedy(query_size, measure, true_reward)
        elif chooser == 'feature_entropy_init_none':
            self.search = False
            self.init_none = True
            self.no_optimize = False
            self.zeros = False
            return self.find_feature_query_greedy(query_size, measure, true_reward)
        elif chooser == 'feature_entropy_search':
            self.search = True
            # self.init_none = False
            self.no_optimize = True
            self.zeros = False
            return self.find_feature_query_greedy(query_size, measure, true_reward)
        elif chooser == 'feature_entropy_search_then_optim':
            self.search = True
            # self.init_none = False
            self.no_optimize = False
            self.zeros = False
            return self.find_feature_query_greedy(query_size, measure, true_reward)
        elif chooser == 'feature_entropy_random_init_none':
            "Chooses feature that minimizes entropy given random weights"
            self.search = False
            self.init_none = True
            self.no_optimize = True
            self.zeros = False
            return self.find_feature_query_greedy(query_size, measure, true_reward)
        elif chooser == 'feature_random':
            "Chooses feature queries and weights at random"
            return self.find_feature_query_greedy(query_size, measure, true_reward, random_query=True)
        elif chooser == 'feature_entropy_zeros_init_none':
            self.search = False
            self.init_none = True
            self.no_optimize = True
            self.zeros = True
            return self.find_feature_query_greedy(query_size, measure, true_reward)
        else:
            raise NotImplementedError('Calling unimplemented query chooser: ' + str(chooser))

    def find_discrete_query(
            self, query_size, measure, true_reward, growth_rate=None,
            full_query=False, random_query=False, exhaustive_query=False):
        """Computes a random or full query or calls a function to greedily grow a query until it reaches query_size.
        """
        if full_query:
            if self.args.full_IRD_subsample_belief == 'yes':
                # TODO(soerenmind): prevent decreasing query size for double samples?
                query_matrix_sample, log_prior_sample = self.sample_true_reward_matrix()
                feature_exp_input = self.cache_feature_expectations(query_matrix_sample)
                query_size = len(query_matrix_sample)
            elif self.args.full_IRD_subsample_belief == 'uniform':
                query_matrix_sample, log_prior_sample = self.sample_true_reward_matrix(uniform_sampling=True)
                feature_exp_input = self.cache_feature_expectations(query_matrix_sample)
                query_size = len(query_matrix_sample)
            elif self.args.full_IRD_subsample_belief == 'no':
                best_query = self.inference.reward_space_proxy
                query_size = len(best_query)
            else:
                raise ValueError('unknown full query method')
        elif random_query:
            best_query = [choice(self.inference.reward_space_proxy) for _ in range(query_size)]
        # Find best query by greedy or exhaustive search
        elif exhaustive_query:
            best_query = self.build_discrete_query(
                query_size, measure, growth_rate, self.extend_with_discretization, exhaustive_query=True)
        else:
            best_query = self.build_discrete_query(
                query_size, measure, growth_rate, self.extend_with_discretization, exhaustive_query=False)

        time_last_query_found = time.clock()

        desired_outputs = [measure, 'true_log_posterior', 'true_entropy', 'post_avg']
        # Set model inputs if they're not set
        if not (full_query and self.args.full_IRD_subsample_belief != 'no'):
            idx = [self.inference.reward_index_proxy[tuple(reward)] for reward in best_query]
            feature_exp_input = self.inference.feature_exp_matrix[idx, :]
        true_reward_matrix, log_prior = self.get_true_reward_space(no_subsampling=True)
        model = self.get_model(query_size, measure, no_planning=True)
        best_objective, true_log_posterior, true_entropy, post_avg = model.compute(
            desired_outputs, self.sess, None, None, log_prior,
            feature_expectations_input=feature_exp_input,
            true_reward=true_reward, true_reward_matrix=true_reward_matrix)

        print('Best objective found with a discrete query: ' + str(best_objective[0][0]))
        return None, best_objective[0][0], true_log_posterior, true_entropy[0], post_avg, time_last_query_found

    def build_discrete_query(self, query_size, measure, growth_rate, extend_fn, exhaustive_query=False):
        """Builds a discrete query by starting from the empty query and calling
        extend_fn to add growth_rate rewards to it until it reaches query_size
        rewards.

        Requires query_size >= 2.
        Assuming extend_fn adds exactly as many rewards to the query as asked,
        it is guaranteed that the returned query is of size query_size.
        """
        best_query = []
        while len(best_query) < query_size:
            size_increase = min(growth_rate, query_size - len(best_query))
            # Discrete queries of size 1 make no sense, so increase to size 2
            if len(best_query) == 0 and size_increase == 1:
                size_increase = 2
            # if growth_rate > 1:
            #     exhaustive = True
            best_query, _ = extend_fn(best_query, size_increase, measure, exhaustive_query)
        return best_query

    def extend_with_discretization(self, curr_query, num_to_add, measure, exhaustive_query):
        best_objective, best_query = float("inf"), None

        # Select set of extensions to consider
        if num_to_add == 1:  # Consider whole proxy space
            query_extensions = [[proxy] for proxy in self.inference.reward_space_proxy]
        elif num_to_add == 2 and not exhaustive_query:  # Consider random combinations for greedy
            num_queries_max = 2 * len(self.inference.reward_space_proxy)
            query_extensions = self.generate_set_of_queries(num_to_add, num_queries_max)
        elif num_to_add >= 2 and exhaustive_query:  # Consider self.num_queries_max for exhaustive search
            query_extensions = self.generate_set_of_queries(num_to_add)
        else:
            raise ValueError('Must add >0 proxies to query (may have selected growth rate >2 for greedy).')

        true_reward_matrix, log_prior = self.get_true_reward_space()
        model = self.get_model(len(curr_query) + num_to_add, measure, no_planning=True)
        for query in query_extensions:
            query = curr_query + query  # query must be LIST of one or more arrays
            idx = [self.inference.reward_index_proxy[tuple(reward)] for reward in query]
            feature_exp_input = self.inference.feature_exp_matrix[idx, :]

            # Compute objective
            objective = model.compute(
                [measure], self.sess, None, None, log_prior,
                feature_expectations_input=feature_exp_input,
                true_reward_matrix=true_reward_matrix)

            if objective[0][0][0] < best_objective:
                best_objective = objective
                best_query = query
        print('Objective for size {s}: '.format(s=len(best_query)) + str(best_objective[0][0][0]))
        return best_query, best_objective[0][0][0]

    def find_discrete_query_with_optimization(
            self, query_size, measure, true_reward, growth_rate=None):
        best_query = self.build_discrete_query(
            query_size, measure, growth_rate, self.extend_with_optimization)

        time_last_query_found = time.clock

        desired_outputs = [measure, 'true_log_posterior', 'true_entropy', 'post_avg']
        true_reward_matrix, log_prior = self.get_true_reward_space(no_subsampling=True)
        mdp = self.inference.mdp
        model = self.get_model(query_size, measure)
        best_objective, true_log_posterior, true_entropy, post_avg = model.compute(
            desired_outputs, self.sess, mdp, best_query, log_prior,
            true_reward=true_reward, true_reward_matrix=true_reward_matrix)

        print('Best objective found with optimized discrete query: ' + str(best_objective[0][0]))
        return best_query, best_objective[0][0], true_log_posterior, true_entropy[0], post_avg, time_last_query_found

    def extend_with_optimization(self, curr_query, num_to_add, measure, exhaustive_query=False):
        true_reward_matrix, log_prior = self.get_true_reward_space()
        desired_outputs = [measure, 'weights_to_train']
        mdp = self.inference.mdp
        dim, steps = self.args.feature_dim, self.args.num_iters_optim
        model = self.get_model(
            len(curr_query) + num_to_add, measure, num_unknown=num_to_add, optimize=True)
        model.initialize(self.sess)
        objective, optimal_new_rewards = model.compute(
            desired_outputs, self.sess, mdp, curr_query, log_prior,
            weight_inits=np.random.randn(num_to_add, dim), gradient_steps=steps,
            # gradient_logging_outputs=[measure, 'weights_to_train'],
            gradient_logging_outputs=[measure],
            true_reward_matrix=true_reward_matrix)
        query = curr_query + list(optimal_new_rewards)
        # TODO(sorenmind): return true_entropy objective
        print('Objective for size {s}: '.format(s=len(query)) + str(objective[0][0]))
        return query, objective[0][0]

    def find_next_feature(self, curr_query, curr_weights, measure, max_query_size):
        mdp = self.inference.mdp
        desired_outputs = [measure, 'weights_to_train', 'feature_exps']
        features = [i for i in range(self.args.feature_dim) if i not in curr_query]

        best_objective, best_objective_plus_cost, best_objective_disc = float("inf"), float("inf"), float("inf")
        best_query, best_optimal_weights, best_feature_exps = None, None, None
        model = self.get_model(
            len(curr_query) + 1, measure, discrete=False, optimize=True)
        true_reward_matrix, log_prior = self.get_true_reward_space()
        self.optim_diff = []
        ent = -np.dot(np.exp(log_prior), log_prior)
        lr = ent.round(0) if ent > 1 else ent.round(1)
        for i, feature in enumerate(features):
            # Resampling weights for each feature
            model.initialize(self.sess)
            query = curr_query + [feature]
            weights = None
            if not self.search:

                # Set weight inits
                num_fixed = self.args.feature_dim - len(query)
                if not self.init_none:
                    if curr_weights is not None:
                        weights = list(curr_weights[:i]) + list(curr_weights[i + 1:])
                elif self.zeros:
                    weights = list(np.zeros(num_fixed))
                # Initialize with random weights
                else:
                    weights = self.sample_weights('init', num_fixed)

                # Set gradient steps
                gd_steps_if_optim = self.args.num_iters_optim
                if self.no_optimize:
                    gd_steps = 0
                elif self.args.only_optim_biggest:
                    if len(query) < max_query_size:
                        gd_steps = 0
                    else:
                        gd_steps = gd_steps_if_optim
                else:
                    gd_steps = gd_steps_if_optim

                # Calculate (optimized) objective
                # objective_before_optim = model.compute(
                #     desired_outputs, self.sess, mdp, query, log_prior,
                #     weights, lr=lr,
                #     true_reward_matrix=true_reward_matrix)
                objective, optimal_weights, feature_exps = model.compute(
                    desired_outputs, self.sess, mdp, query, log_prior,
                    weights, gradient_steps=gd_steps, lr=lr,
                    # gradient_logging_outputs=[measure, 'weights_to_train[:3]'],#, 'gradients[:4]'],#, 'state_probs_cut'],
                    true_reward_matrix=true_reward_matrix)
                # self.optim_diff.append(objective[0][0] - objective_before_optim[0][0])
                query_cost = self.cost_of_asking * len(query)
                objective_plus_cost = objective + query_cost
            # Find weights by search over samples
            else:
                # Set gradient steps and num_search
                gd_steps_if_optim = self.args.num_iters_optim // 2
                num_search_if_optim = self.args.num_iters_optim * (
                        1 + self.no_optimize)  # GD steps take ca 2x as long as forward passes
                # Optionally only optimize if at maximum query size
                if self.args.only_optim_biggest:
                    if len(query) < max_query_size:
                        gd_steps = 0
                        num_search = 1
                    else:
                        gd_steps = gd_steps_if_optim
                        num_search = num_search_if_optim
                else:
                    gd_steps = gd_steps_if_optim
                    num_search = num_search_if_optim

                # Random search
                objective, optimal_weights, feature_exps = \
                    self.random_search(desired_outputs, query, num_search, model, log_prior, mdp, true_reward_matrix)
                objective_search = objective.copy()

                # Optimize from best sample if desired
                if not self.no_optimize:
                    objective, optimal_weights, feature_exps = model.compute(
                        desired_outputs, self.sess, mdp, query, log_prior,
                        optimal_weights, gradient_steps=gd_steps, lr=lr,
                        # gradient_logging_outputs=[measure, 'weights_to_train[:3]'],#, 'gradients[:4]'],#, 'state_probs_cut'],
                        true_reward_matrix=true_reward_matrix)
                objective_plus_cost = objective + self.cost_of_asking * len(query)
                self.optim_diff.append(objective[0][0] - objective_search[0][0])

            # print('Model outputs calculated')
            if objective_plus_cost <= best_objective_plus_cost + 1e-14:
                best_objective = objective
                best_objective_plus_cost = objective_plus_cost
                best_optimal_weights = optimal_weights
                best_query = query
                best_feature_exps = feature_exps
        print('Objective for size {s}: '.format(s=len(best_query)) + str(best_objective[0][0]))

        return best_query, best_optimal_weights, best_feature_exps

    # @profile
    def find_feature_query_greedy(self, query_size, measure, true_reward, random_query=False):
        """Returns feature query of size query_size that minimizes the objective (e.g. posterior entropy)."""
        mdp = self.inference.mdp
        cost_of_asking = self.cost_of_asking  # could use this to decide query length
        best_query = []
        best_weights = None
        while len(best_query) < query_size:
            if random_query:
                best_query, best_weights, feature_exps = self.add_random_feature(best_query, measure)
            else:
                best_query, best_weights, feature_exps = self.find_next_feature(
                    best_query, best_weights, measure, query_size)
            print('Query length increased to {s}'.format(s=len(best_query)))

        print('query found')

        # For the chosen query, get posterior from human answer. If using human input, replace with feature exps or trajectories.
        desired_outputs = [measure, 'true_log_posterior', 'true_entropy', 'post_avg']
        true_reward_matrix, log_prior = self.get_true_reward_space(no_subsampling=True)

        time_last_query_found = time.clock()

        disc_size = self.args.discretization_size_human
        model = self.get_model(query_size, measure, discrete=False, discretization_size=disc_size, optimize=True)
        model.initialize(self.sess)
        objective, true_log_posterior, true_entropy, post_avg = model.compute(
            desired_outputs, self.sess, mdp, best_query, log_prior,
            weight_inits=best_weights,
            true_reward=true_reward, true_reward_matrix=true_reward_matrix)
        print('Best full posterior objective found (human discretization, continuous): ' + str(objective[0][0]))

        return best_query, objective[0][0], true_log_posterior, true_entropy[0], post_avg, time_last_query_found

    def add_random_feature(self, curr_query, measure):
        """Same as self.find_next_feature, except the added feature is not optimized, i.e. random."""
        mdp = self.inference.mdp
        desired_outputs = [measure, 'weights_to_train', 'feature_exps']
        features = [i for i in range(self.args.feature_dim) if i not in curr_query]
        model = self.get_model(
            len(curr_query) + 1, measure, discrete=False, optimize=True)
        true_reward_matrix, log_prior = self.get_true_reward_space()

        query = curr_query + [choice(features)]

        # Initialize with random weights
        num_fixed = self.args.feature_dim - len(query)
        weights = self.sample_weights('init', num_fixed)

        objective, weights, feature_exps = model.compute(
            desired_outputs, self.sess, mdp, query, log_prior,
            weights,
            true_reward_matrix=true_reward_matrix)

        return query, weights, feature_exps

    def random_search(self, desired_outputs, query, num_search, model, log_prior, mdp, true_reward_matrix):
        """Returns the objective, weights, and feature expectations that minimized the objective in a random search."""
        best_objective_disc = float("inf")
        for _ in range(num_search):
            num_fixed = self.args.feature_dim - len(query)

            # Sample weights
            other_weights = self.sample_weights('search', num_fixed)

            # Calculate objective
            objective_disc, optimal_weights_disc, feature_exps_disc = model.compute(
                desired_outputs, self.sess, mdp, query, log_prior,
                other_weights, true_reward_matrix=true_reward_matrix)

            # Update best variables
            if objective_disc <= best_objective_disc:
                best_objective_disc = objective_disc
                best_optimal_weights_disc = optimal_weights_disc
                best_feature_exps_disc = feature_exps_disc

        return best_objective_disc, best_optimal_weights_disc, best_feature_exps_disc

    def get_other_weights_samples(self, length):
        """Generates random other weights from given discretization."""
        num_posneg_vals = (self.args.discretization_size // 2)
        const = 9 // num_posneg_vals
        f_range = range(-num_posneg_vals * const, 10, const)
        # print 'Using', f_range, 'to discretize the feature'
        assert len(f_range) == self.args.discretization_size
        # other_weights = np.random.randint(-9,10,size=length)
        other_weights = np.random.choice(f_range, size=length)
        # list(product(f_range, repeat=query_size))
        return other_weights

    def sample_weights(self, search_or_init, num_fixed):
        if search_or_init == 'search':
            if self.args.weights_dist_search == 'normal':
                weights = np.random.randn(num_fixed)
            elif self.args.weights_dist_search == 'normal2':
                weights = 2 * np.random.randn(num_fixed)
            elif self.args.weights_dist_search == 'normal4':
                weights = 4 * np.random.randn(num_fixed)
            elif self.args.weights_dist_search == 'uniform':
                weights = self.get_other_weights_samples(num_fixed)
            else:
                raise ValueError('weight distribution unknown')
        elif search_or_init == 'init':
            if self.args.weights_dist_init == 'normal':
                weights = np.random.randn(num_fixed)
            elif self.args.weights_dist_search == 'normal2':
                weights = 2 * np.random.randn(num_fixed)
            elif self.args.weights_dist_search == 'normal4':
                weights = 4 * np.random.randn(num_fixed)
            elif self.args.weights_dist_init == 'uniform':
                weights = self.get_other_weights_samples(num_fixed)
            else:
                raise ValueError('weights distribution unknown')
        else:
            raise ValueError('weights sampling method unknown')

        return weights

    def set_inference(self, inference, cache_feature_exps):
        self.inference = inference
        if cache_feature_exps:
            self.cache_feature_expectations()

    def generate_set_of_queries(self, query_size, num_queries_max=None):
        if num_queries_max == None:
            # Use hyperparameter for exhaustive chooser
            num_queries_max = self.num_queries_max
        num_queries = comb(len(self.inference.reward_space_proxy), query_size)
        if num_queries > num_queries_max:
            return [list(random_combination(self.inference.reward_space_proxy, query_size)) for _ in
                    range(num_queries_max)]
        return [list(x) for x in combinations(self.inference.reward_space_proxy, query_size)]

    def get_true_reward_space(self, no_subsampling=False):
        if self.args.subsampling and not no_subsampling:
            # num_subsamples = self.args.num_subsamples
            # Get true reward samples to optimize with
            true_reward_matrix, log_prior = self.sample_true_reward_matrix()
            # log_prior = np.log(np.ones(num_subsamples) / num_subsamples)
        else:
            true_reward_matrix = self.inference.true_reward_matrix
            log_prior = self.inference.log_prior
        return true_reward_matrix, log_prior

    def sample_true_reward_matrix(self, uniform_sampling=False):
        num_subsamples = self.args.num_subsamples
        if uniform_sampling:
            probs = np.ones(len(self.inference.log_prior))
            weighting = False
        else:
            log_probs = self.inference.log_prior
            probs = np.exp(log_probs)
            weighting = self.args.weighting
        probs = probs / probs.sum()
        choices = np.random.choice(self.args.size_true_space, p=probs, size=num_subsamples)
        if weighting:
            unique_sample_idx, counts = np.unique(choices, return_counts=True)

            weighted_probs = np.ones(len(counts)) * counts
            weighted_probs = weighted_probs / weighted_probs.sum()
            return self.inference.true_reward_matrix[unique_sample_idx], np.log(weighted_probs)
        else:
            unif_log_prior = np.log(np.ones(num_subsamples) / num_subsamples)
            return self.inference.true_reward_matrix[choices], unif_log_prior

    def get_model(self, query_size, objective, num_unknown=None,
                  discrete=True, optimize=False, no_planning=False, cache=True, rational_planner=False,
                  discretization_size=None):
        mdp = self.inference.mdp
        height, width = None, None
        # TODO: Replace mdp.type with self.args.mdp_type
        if mdp.type == 'gridworld':
            height, width = mdp.height, mdp.width
        dim, gamma, lr = self.args.feature_dim, self.args.gamma, self.args.lr
        beta, beta_planner = self.args.beta, self.args.beta_planner
        if rational_planner:
            beta_planner = 'inf'
        num_iters = self.args.value_iters
        if discretization_size is None:
            discretization_size = self.args.discretization_size
        true_reward_space_size = None
        # true_reward_space_size = len(self.inference.true_reward_matrix)
        key = (no_planning, mdp.type, dim, gamma, query_size,
               discretization_size, true_reward_space_size, num_unknown, beta,
               beta_planner, lr, discrete, optimize, height, width, num_iters, objective)
        if key in self.model_cache:
            return self.model_cache[key]

        print('building model...')
        if no_planning:
            model = NoPlanningModel(
                dim, gamma, query_size, discretization_size,
                true_reward_space_size, num_unknown, beta, beta_planner,
                objective, lr, discrete, optimize, self.args)
        elif mdp.type == 'bandits':
            print('Calling BanditsModel')
            model = BanditsModel(
                dim, gamma, query_size, discretization_size,
                true_reward_space_size, num_unknown, beta, beta_planner,
                objective, lr, discrete, optimize, self.args)
        elif mdp.type == 'gridworld':
            model = GridworldModel(
                dim, gamma, query_size, discretization_size,
                true_reward_space_size, num_unknown, beta, beta_planner,
                objective, lr, discrete, optimize, mdp.height, mdp.width,
                num_iters, self.args)
        else:
            raise ValueError('Unknown model type: ' + str(mdp.type))

        if cache:
            self.model_cache[key] = model
            print('Model built and cached!')
        return model


class Experiment(object):
    """"""

    def __init__(self, true_rewards, query_size, num_queries_max, args, choosers, SEED, exp_params,
                 train_inferences, test_inferences, prior_avg):
        self.query_size = query_size
        self.num_queries_max = num_queries_max
        self.choosers = choosers
        self.seed = SEED
        self.t_0 = time.clock()
        self.query_chooser = Query_Chooser(num_queries_max, args, t_0=self.t_0)
        self.results = {}
        # Add variance
        self.measures = ['true_entropy', 'test_regret', 'norm post_avg-true', 'post_regret', 'perf_measure',
                         'std_proxy', 'mean_proxy', 'std_goal', 'mean_goal']
        self.cum_measures = ['cum_test_regret', 'cum_post_regret']
        curr_time = str(datetime.datetime.now())[:-6]
        self.folder_name = curr_time + '-' + '-'.join([key + '=' + str(val) for key, val in sorted(exp_params.items())])
        self.train_inferences = train_inferences
        self.test_inferences = test_inferences
        self.true_rewards = true_rewards
        self.prior_avg = prior_avg

    # @profile
    def get_experiment_stats(self, num_iter, num_experiments):
        self.results = {}
        post_exp_regret_measurements = [];
        post_regret_measurements = []
        for exp_num in range(num_experiments):
            self.run_experiment(num_iter, exp_num, num_experiments)
            self.write_experiment_results_to_csv(exp_num, num_iter)

        self.write_mean_and_median_results_to_csv(num_experiments, num_iter)

        return self.results

    # @profile
    def run_experiment(self, num_iter, exp_num, num_experiments):
        print(
            "======================================================Experiment {n}/{N}===============================================================".format(
                n=exp_num + 1, N=num_experiments))
        # Initialize variables

        # Set run parameters
        inference = self.train_inferences[exp_num]
        random.seed(self.seed)
        self.seed += 1
        true_reward = self.true_rewards[exp_num]

        # Cache feature_exps for discrete experiments
        cache_feature_exps = any(
            chooser in self.choosers for chooser in ['greedy_discrete', 'exhaustive', 'random', 'full'])
        self.query_chooser.set_inference(inference, cache_feature_exps=cache_feature_exps)

        # Run experiment for each query chooser
        for chooser in self.choosers:
            print("===========================Experiment {n}/{N} for {chooser}===========================".format(
                chooser=chooser, n=exp_num + 1, N=num_experiments))
            inference.reset_prior()

            for i in range(-1, num_iter):
                iter_start_time = time.clock()
                print("==========Iteration: {i}/{m} ({c}). Total time: {t}==========".format(i=i + 1, m=num_iter,
                                                                                             c=chooser,
                                                                                             t=iter_start_time - self.t_0))
                if i > -1:
                    query, perf_measure, true_log_posterior, true_entropy, post_avg, time_last_query_found \
                        = self.query_chooser.find_query(self.query_size, chooser, true_reward)
                    # query = [np.array(proxy) for proxy in query]    # unnecessary?
                    inference.update_prior(None, None, true_log_posterior)
                # Log outcomes before 1st query
                else:
                    query = None
                    true_entropy = np.log(len(inference.prior))
                    perf_measure = float('inf')
                    post_avg = self.prior_avg
                    time_last_query_found = iter_start_time

                # Outcome measures
                iter_end_time = time.clock()
                duration_iter = iter_end_time - iter_start_time
                duration_query_chooser = time_last_query_found - iter_start_time
                # post_exp_regret = self.query_chooser.get_exp_regret_from_query(query=[])
                post_regret = self.compute_regret(post_avg, true_reward,
                                                  inference)  # TODO: Still plans with Python. May use wrong gamma, or trajectory length
                norm_to_true = self.get_normalized_reward_diff(post_avg, true_reward)
                test_regret = self.compute_regret(post_avg, true_reward)
                std_proxy, mean_proxy, std_goal, mean_goal = self.get_posterior_variance(inference)
                print('Test regret: ' + str(test_regret) + ' | Post regret: ' + str(post_regret))

                # Save results
                self.results[chooser, 'true_entropy', i, exp_num], \
                self.results[chooser, 'perf_measure', i, exp_num], \
                self.results[chooser, 'post_regret', i, exp_num], \
                self.results[chooser, 'test_regret', i, exp_num], \
                self.results[chooser, 'norm post_avg-true', i, exp_num], \
                self.results[chooser, 'query', i, exp_num], \
                self.results[chooser, 'time', i, exp_num], \
                self.results[chooser, 'time_query_chooser', i, exp_num], \
                self.results[chooser, 'std_proxy', i, exp_num], \
                self.results[chooser, 'mean_proxy', i, exp_num], \
                self.results[chooser, 'std_goal', i, exp_num], \
                self.results[chooser, 'mean_goal', i, exp_num], \
                    = true_entropy, perf_measure, post_regret, test_regret, norm_to_true, query, duration_iter, duration_query_chooser, \
                      std_proxy, mean_proxy, std_goal, mean_goal

    def get_posterior_variance(self, inference):
        """Gets posterior mean and std for last and 2nd last feature by sampling."""
        args = self.query_chooser.args
        feature_dim = args.feature_dim
        # query_matrix_sample, log_prior_sample = self.query_chooser.sample_true_reward_matrix()
        log_probs = inference.log_prior
        probs = np.exp(log_probs)
        probs = probs / probs.sum()
        choices = np.random.choice(args.size_true_space, p=probs, size=50000)
        # unif_log_prior = np.log(np.ones(10000) / 10000)

        posterior_samples = inference.true_reward_matrix[choices]
        std = np.std(posterior_samples, 0)
        means = np.mean(posterior_samples, 0)

        unique_sample_idx, counts = np.unique(choices, return_counts=True)

        proxy_idx = feature_dim - 2
        goal_idx = feature_dim - 1
        return std[proxy_idx], means[proxy_idx], std[goal_idx], means[goal_idx]

    def compute_regret(self, post_avg, true_reward, inference=None):
        """Computes mean regret from optimizing post_avg across some cached test environments.
        If inference is given, the regret is computed only in inference.mdp (the training environment)."""

        # Compute regret over test mdps
        if inference is None:
            inferences = self.test_inferences
        # Compute regret using training mdp
        else:
            inferences = [inference]

        regrets = np.empty(len(self.test_inferences))
        for i, inference in enumerate(inferences):
            # New method using TF:
            test_mdp = inference.mdp
            planning_model = self.query_chooser.get_model(1, 'entropy',
                                                          rational_planner=self.query_chooser.args.rational_test_planner)

            [post_avg_feature_exps] = planning_model.compute(['feature_exps'], self.query_chooser.sess, test_mdp,
                                                             [list(post_avg)])
            [true_reward_feature_exps] = planning_model.compute(['feature_exps'], self.query_chooser.sess, test_mdp,
                                                                [list(true_reward)])

            optimal_reward = np.dot(true_reward_feature_exps, true_reward)
            test_reward = np.dot(post_avg_feature_exps, true_reward)
            regret = optimal_reward - test_reward
            regrets[i] = regret

            # Old method (using normalized feature exps in Python)
            # test_reward = inference.get_avg_reward(post_avg, true_reward)
            # optimal_reward = inference.get_avg_reward(true_reward, true_reward)
            # regret = optimal_reward - test_reward
            # regrets[i] = regret
            if regret < -1:
                if len(inferences) == 1:
                    text = ' (post_regret)'
                else:
                    text = ' (test_regret)'
                print('Negative regret !!!!!!!')
                print('regret: ' + str(regret) + text)
        return regrets.mean()

    def get_normalized_reward_diff(self, post_avg, true_reward):
        norm_post_avg = (post_avg - post_avg.mean())
        norm_post_avg = norm_post_avg / np.linalg.norm(norm_post_avg, ord=2)
        norm_true = (true_reward - true_reward.mean())
        norm_true = norm_true / np.linalg.norm(norm_true, ord=2)

        return np.linalg.norm(norm_post_avg - norm_true)

    def write_experiment_results_to_csv(self, exp_num, num_iter):
        """Writes a CSV for every chooser for every experiment. The CSV's columns are 'iteration' and all measures in
        self.measures."""
        if not os.path.exists('data/' + self.folder_name):
            os.mkdir('data/' + self.folder_name)
        else:
            Warning('Existing experiment stats overwritten')
        for chooser in self.choosers:
            f = open('data/' + self.folder_name + '/' + chooser + str(exp_num) + '.csv',
                     'w')  # Open CSV in folder with name exp_params
            writer = csv.DictWriter(f, fieldnames=['iteration'] + self.measures + self.cum_measures + ['time',
                                                                                                       'time_query_chooser'])
            writer.writeheader()
            rows = []
            cum_test_regret, cum_post_regret = 0, 0
            for i in range(-1, num_iter):
                csvdict = {}
                csvdict['iteration'] = i
                for measure in self.measures + ['time', 'time_query_chooser']:
                    entry = self.results[chooser, measure, i, exp_num]
                    csvdict[measure] = entry
                    if measure == 'test_regret':
                        cum_test_regret += entry
                        csvdict['cum_test_regret'] = cum_test_regret
                    elif measure == 'post_regret':
                        cum_post_regret += entry
                        csvdict['cum_post_regret'] = cum_post_regret
                rows.append(csvdict)
            writer.writerows(rows)

    def write_mean_and_median_results_to_csv(self, num_experiments, num_iter):
        """Writes a CSV for every chooser averaged (and median-ed, standard-error-ed) across experiments.
        Saves in the same folder as CSVs per experiment. Columns are 'iteration' and all measures in
        self.measures + self.cum_measures + ['time', 'time_query_chooser']."""
        if not os.path.exists('data/' + self.folder_name):
            os.mkdir('data/' + self.folder_name)
        else:
            Warning('Existing experiment stats overwritten')

        # Make files that summarize experiments
        f_mean_all = open('data/' + self.folder_name + '/' + 'all choosers' + '-means-' + '.csv', 'w')
        writer_mean_all_choosers = csv.DictWriter(f_mean_all,
                                                  fieldnames=['iteration'] + self.measures + self.cum_measures + [
                                                      'time', 'time_query_chooser'])

        f_median_all = open('data/' + self.folder_name + '/' + 'all choosers' + '-medians-' + '.csv', 'w')
        writer_medians_all_choosers = csv.DictWriter(f_median_all,
                                                     fieldnames=['iteration'] + self.measures + self.cum_measures + [
                                                         'time', 'time_query_chooser'])

        f_sterr_all = open('data/' + self.folder_name + '/' + 'all choosers' + '-sterr-' + '.csv', 'w')
        writer_sterr_all_choosers = csv.DictWriter(f_sterr_all,
                                                   fieldnames=['iteration'] + self.measures + self.cum_measures + [
                                                       'time', 'time_query_chooser'])

        for chooser in self.choosers:
            f_mean = open('data/' + self.folder_name + '/' + chooser + '-means-' + '.csv', 'w')
            f_median = open('data/' + self.folder_name + '/' + chooser + '-medians-' + '.csv', 'w')
            f_sterr = open('data/' + self.folder_name + '/' + chooser + '-sterr-' + '.csv', 'w')

            writer_mean = csv.DictWriter(f_mean, fieldnames=['iteration'] + self.measures + self.cum_measures + ['time',
                                                                                                                 'time_query_chooser'])
            writer_median = csv.DictWriter(f_median,
                                           fieldnames=['iteration'] + self.measures + self.cum_measures + ['time',
                                                                                                           'time_query_chooser'])
            writer_sterr = csv.DictWriter(f_sterr,
                                          fieldnames=['iteration'] + self.measures + self.cum_measures + ['time',
                                                                                                          'time_query_chooser'])

            writer_mean.writeheader()
            writer_median.writeheader()
            writer_sterr.writeheader()
            rows_mean = []
            rows_median = []
            rows_sterr = []
            cum_test_regret = np.zeros(num_experiments)
            cum_post_regret = np.zeros(num_experiments)

            for i in range(-1, num_iter):
                csvdict_mean = {}
                csvdict_median = {}
                csvdict_sterr = {}

                csvdict_mean['iteration'] = i
                csvdict_median['iteration'] = i
                csvdict_sterr['iteration'] = i

                for measure in self.measures + ['time', 'time_query_chooser']:
                    entries = np.zeros(num_experiments)
                    for exp_num in range(num_experiments):
                        entry = self.results[chooser, measure, i, exp_num]
                        entries[exp_num] = entry
                        if measure == 'test_regret':
                            cum_test_regret[exp_num] += entry
                        if measure == 'post_regret':
                            cum_post_regret[exp_num] += entry
                    csvdict_mean['cum_test_regret'] = cum_test_regret.mean()
                    csvdict_mean['cum_post_regret'] = cum_post_regret.mean()
                    csvdict_sterr['cum_test_regret'] = np.std(cum_test_regret) / np.sqrt(len(entries))
                    csvdict_sterr['cum_post_regret'] = np.std(cum_post_regret) / np.sqrt(len(entries))
                    csvdict_mean[measure] = np.mean(entries)
                    csvdict_median[measure] = np.median(entries)
                    csvdict_sterr[measure] = np.std(entries) / np.sqrt(len(entries))
                rows_mean.append(csvdict_mean)
                rows_median.append(csvdict_median)
                rows_sterr.append(csvdict_sterr)
            writer_mean.writerows(rows_mean)
            writer_median.writerows(rows_median)
            writer_sterr.writerows(rows_sterr)

            # Also append statistics for this chooser to CSV with all_choosers_mean
            writer_mean_all_choosers.writerow({'iteration': chooser})
            writer_mean_all_choosers.writeheader()
            writer_mean_all_choosers.writerows(rows_mean)

            # Also append statistics for this chooser to CSV with all_choosers_medians
            writer_medians_all_choosers.writerow({'iteration': chooser})
            writer_medians_all_choosers.writeheader()
            writer_medians_all_choosers.writerows(rows_median)

            # Also append statistics for this chooser to CSV with all_choosers_sterr
            writer_sterr_all_choosers.writerow({'iteration': chooser})
            writer_sterr_all_choosers.writeheader()
            writer_sterr_all_choosers.writerows(rows_sterr)
