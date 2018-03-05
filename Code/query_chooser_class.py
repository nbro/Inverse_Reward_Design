from itertools import combinations, product
from scipy.special import comb
from random import choice, sample, seed
import numpy as np
import time
# for test environment
from gridworld import NStateMdp, GridworldEnvironment, Direction, NStateMdpHardcodedFeatures, NStateMdpGaussianFeatures,\
    NStateMdpRandomGaussianFeatures, GridworldMdpWithDistanceFeatures, GridworldMdp
from agents import ImmediateRewardAgent, DirectionalAgent, OptimalAgent
from inference_class import InferenceDiscrete
import csv
import os
import datetime
from planner import GridworldModel, BanditsModel, NoPlanningModel
import tensorflow as tf
from itertools import product


def random_combination(iterable, r):
    """Random selection from itertools.combinations(iterable, r)"""
    pool = tuple(iterable)
    n = len(pool)
    indices = sorted(sample(xrange(n), r))
    return tuple(pool[i] for i in indices)

def time_function(function, input):
    "Calls function and returns time it took"
    start = time.clock()
    function(input)
    deltat = time.clock() - start
    return deltat


class Query_Chooser(object):
    def __init__(self):
        pass

class Query_Chooser_Subclass(Query_Chooser):
    def __init__(self, reward_space_proxy, num_queries_max, args, prior=None, cost_of_asking=0, t_0 = None):
        super(Query_Chooser_Subclass, self).__init__()
        # self.inference = inference
        self.reward_space_proxy = reward_space_proxy
        # self.prior = prior
        self.cost_of_asking = cost_of_asking
        self.num_queries_max = num_queries_max
        self.args = args    # all args
        self.t_0 = t_0
        self.model_cache = {}
        self.sess = tf.Session()

    # def cache_feature_expectations(self):
    #     """Calculates feature expectations for all proxies and stores them in the dictionary
    #     inference.feature_expectations_dict. This function is only needed if you want to front-load these computations."""
    #     for proxy in self.reward_space_proxy:
    #         feature_expectations = self.inference.get_feature_expectations(proxy)

    def cache_feature_expectations(self, reward_space):
        """Is run in self.__init__. Computes feature expectations for each proxy using TF and stores them in
        inference.feature_expectations_matrix."""
        proxy_space = [list(reward) for reward in reward_space]
        print('building graph. Total experiment time: {t}'.format(t=time.clock()-self.t_0))
        model = self.get_model(len(proxy_space))
        model.initialize(self.sess)

        desired_outputs = ['feature_exps']
        mdp = self.inference.mdp
        print('Computing model outputs. Total experiment time: {t}'.format(t=time.clock()-self.t_0))
        [feature_exp_matrix] = model.compute(
            desired_outputs, self.sess, mdp, proxy_space, self.inference.log_prior)
        self.inference.feature_exp_matrix = feature_exp_matrix
        print('Done computing model outputs. Total experiment time: {t}'.format(t=time.clock()-self.t_0))





    def generate_set_of_queries(self, query_size):
        num_queries = comb(len(self.reward_space_proxy), query_size)
        if num_queries > self.num_queries_max:
            return [list(random_combination(self.reward_space_proxy, query_size)) for _ in range(self.num_queries_max)]
        return [list(x) for x in combinations(self.reward_space_proxy, query_size)]

    # @profile
    def find_query(self, query_size, chooser, true_reward):
        """Calls query chooser specified by chooser (string)."""
        # if chooser == 'maxmin':
        #     return self.find_query_feature_diff(query_size)
        if chooser == 'test_graph':
            self.test_graph(query_size, 'variance', true_reward)
        if chooser == 'exhaustive_entropy':
            return self.find_discrete_query(query_size, 'entropy', true_reward, growth_rate=query_size)
        # elif chooser == 'greedy_regret':
        #     return self.find_best_query_greedy(query_size, true_reward=true_reward)
        elif chooser == 'random':
            return self.find_discrete_query(query_size, 'entropy', true_reward, random_query=True)
        elif chooser == 'full':
            return self.find_discrete_query(query_size, 'entropy', true_reward, full_query=True)
        # elif chooser == 'no_query':
        #     return [], self.get_exp_regret_from_query([]), None
        # elif chooser == 'greedy_exp_reward':
        #     return self.find_best_query_greedy(query_size, total_reward=True, true_reward=true_reward)
        elif chooser == 'greedy_entropy_discrete_tf':
            return self.find_discrete_query(query_size, 'entropy', true_reward, growth_rate=1)
        elif chooser == 'incremental_optimize':
            return self.find_discrete_query_with_optimization(
                query_size, 'entropy', true_reward, growth_rate=1)
        elif chooser == 'joint_optimize':
            return self.find_discrete_query_with_optimization(
                query_size, 'entropy', true_reward, growth_rate=query_size)
        # elif chooser == 'greedy_entropy':
            # return self.find_best_query_greedy(query_size, entropy=True, true_reward=true_reward)
        elif chooser == 'feature_entropy':
            return self.find_feature_query_greedy(query_size, 'entropy', true_reward)
        elif chooser == 'feature_variance':
            return self.find_feature_query_greedy(query_size, 'variance', true_reward)
        else:
            raise NotImplementedError('Calling unimplemented query chooser')


    def build_discrete_query(self, query_size, measure, growth_rate, extend_fn):
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
            best_query, _ = extend_fn(best_query, size_increase, measure)
        return best_query

    def find_discrete_query(
            self, query_size, measure, true_reward, growth_rate=None,
            full_query=False, random_query=False):
        """Computes a query by greedily growing the query by growth_rate
        features until reaching query_size features.
        """
        if full_query:
            best_query = self.reward_space_proxy
            query_size = len(self.reward_space_proxy)
        elif random_query:
            best_query = [choice(self.reward_space_proxy) for _ in range(query_size)]
        else:
            best_query = self.build_discrete_query(
                query_size, measure, growth_rate, self.extend_with_discretization)

        desired_outputs = [measure, 'true_log_posterior', 'true_entropy', 'post_avg']
        true_reward_matrix, log_prior = self.get_true_reward_space(no_subsampling=True)
        idx = [self.inference.reward_index_proxy[tuple(reward)] for reward in best_query]
        feature_exp_input = self.inference.feature_exp_matrix[idx, :]
        model = self.get_model(query_size, no_planning=True)
        best_objective, true_log_posterior, true_entropy, post_avg = model.compute(
            desired_outputs, self.sess, None, None, log_prior,
            feature_expectations_input=feature_exp_input,
            true_reward=true_reward, true_reward_matrix=true_reward_matrix)



        print('Best objective found with a discrete query: ' + str(best_objective[0][0]))
        return best_query, best_objective[0][0], true_log_posterior, true_entropy[0], post_avg

    def extend_with_discretization(self, curr_query, num_to_add, measure):
        best_objective, best_query = float("inf"), None
        query_extensions = self.generate_set_of_queries(num_to_add)
        true_reward_matrix, log_prior = self.get_true_reward_space()
        model = self.get_model(len(curr_query) + num_to_add, no_planning=True)
        for query in query_extensions:
            query = curr_query + query
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

        desired_outputs = [measure, 'true_log_posterior', 'true_entropy', 'post_avg']
        true_reward_matrix, log_prior = self.get_true_reward_space(no_subsampling=True)
        mdp = self.inference.mdp
        model = self.get_model(query_size)
        best_objective, true_log_posterior, true_entropy, post_avg = model.compute(
            desired_outputs, self.sess, mdp, best_query, log_prior,
            true_reward=true_reward, true_reward_matrix=true_reward_matrix)

        print('Best objective found with optimized discrete query: ' + str(best_objective[0][0]))
        return best_query, best_objective[0][0], true_log_posterior, true_entropy[0], post_avg

    def extend_with_optimization(self, curr_query, num_to_add, measure):
        true_reward_matrix, log_prior = self.get_true_reward_space()
        desired_outputs = [measure, 'weights_to_train']
        mdp = self.inference.mdp
        dim, steps = self.args.feature_dim, self.args.num_iters_optim
        model = self.get_model(
            len(curr_query) + num_to_add, num_unknown=num_to_add, optimize=True)
        model.initialize(self.sess)
        objective, optimal_new_rewards = model.compute(
            desired_outputs, self.sess, mdp, curr_query, log_prior,
            weight_inits=np.random.randn(num_to_add, dim), gradient_steps=steps,
            gradient_logging_outputs=[measure],
            true_reward_matrix=true_reward_matrix)
        query = curr_query + list(optimal_new_rewards)
        print('Objective for size {s}: '.format(s=len(query)) + str(objective[0][0]))
        return query, objective[0][0]

    def sample_true_reward_matrix(self):
        # Problem: Samples will be likelihood-weighted in graph. Gotta feed in uniform prior.

        num_subsamples = self.args.num_subsamples
        log_probs = self.inference.log_prior
        probs = np.exp(log_probs)
        probs = probs / probs.sum()
        choices = np.random.choice(self.args.size_true_space, p=probs, size=num_subsamples)

        if self.args.weighting:
            unique_sample_idx, counts = np.unique(choices, return_counts=True)

            # Not using log probabilities
            weighted_probs = probs[unique_sample_idx] * counts
            weighted_probs = weighted_probs / weighted_probs.sum()
            return self.inference.true_reward_matrix[unique_sample_idx], np.log(weighted_probs)
        else:
            unif_log_prior = np.log(np.ones(num_subsamples) / num_subsamples)
            return self.inference.true_reward_matrix[choices], unif_log_prior


    def find_next_feature(self, curr_query, curr_weights, measure, true_reward):
        mdp = self.inference.mdp
        desired_outputs = [measure, 'weights_to_train', 'feature_exps']
        features = [i for i in range(self.args.feature_dim) if i not in curr_query]

        best_objective, best_objective_plus_cost = float("inf"), float("inf")
        best_query, best_optimal_weights, best_feature_exps = None, None, None
        model = self.get_model(
            len(curr_query) + 1, discrete=False, optimize=True)

        true_reward_matrix, log_prior = self.get_true_reward_space()

        model.initialize(self.sess)
        for i, feature in enumerate(features):
            query = curr_query+[feature]
            weights = None
            if curr_weights is not None:
                weights = list(curr_weights[:i]) + list(curr_weights[i+1:])

            objective, optimal_weights, feature_exps = model.compute(
                desired_outputs, self.sess, mdp, query, log_prior,
                weights, gradient_steps=self.args.num_iters_optim,
                gradient_logging_outputs=[measure], true_reward=true_reward,
                true_reward_matrix=true_reward_matrix)
            query_cost = self.cost_of_asking * len(query)
            objective_plus_cost = objective + query_cost
            print('Model outputs calculated')
            if objective_plus_cost <= best_objective_plus_cost + 1e-14:
                best_objective = objective
                best_objective_plus_cost = objective_plus_cost
                best_optimal_weights = optimal_weights
                best_query = query
                best_feature_exps = feature_exps
        return best_query, best_optimal_weights, best_feature_exps



    # @profile
    def find_feature_query_greedy(self, query_size, measure, true_reward):
        """Returns feature query of size query_size that minimizes the objective (e.g. posterior entropy)."""
        mdp = self.inference.mdp
        cost_of_asking = self.cost_of_asking    # could use this to decide query length
        best_query = []
        feature_dim = self.args.feature_dim
        best_weights = None
        while len(best_query) < query_size:
            best_query, best_weights, feature_exps = self.find_next_feature(
                best_query, best_weights, measure, true_reward)
            print 'Query length increased to {s}'.format(s=len(best_query))

        print('query found')
        # For the chosen query, get posterior from human answer. If using human input, replace with feature exps or trajectories.
        # Add: Get all measures for data recording?
        desired_outputs = [measure, 'true_log_posterior','true_entropy', 'post_avg']
        true_reward_matrix, log_prior = self.get_true_reward_space(no_subsampling=True)
        model = self.get_model(query_size, discrete=False)
        model.initialize(self.sess)
        objective, true_log_posterior, true_entropy, post_avg = model.compute(
            desired_outputs, self.sess, mdp, best_query, log_prior,
            feature_expectations_input=feature_exps,
            true_reward=true_reward, true_reward_matrix=true_reward_matrix)
        #return best_query, objective, true_posterior, true_entropy[0]
        return best_query, objective, true_log_posterior, post_avg



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



    def get_model(self, query_size, discretization_const=2, num_unknown=None,
                  discrete=True, optimize=False, no_planning=False):
        mdp = self.inference.mdp
        height, width = None, None
        # TODO: Replace mdp.type with self.args.mdp_type
        if mdp.type == 'gridworld':
            height, width = mdp.height, mdp.width
        dim, gamma, lr = self.args.feature_dim, self.args.gamma, self.args.lr
        beta, beta_planner = self.args.beta, self.args.beta_planner
        num_iters = self.args.value_iters
        true_reward_space_size = None
        # true_reward_space_size = len(self.inference.true_reward_matrix)
        key = (no_planning, mdp.type, dim, gamma, query_size,
               discretization_const, true_reward_space_size, num_unknown, beta,
               beta_planner, lr, discrete, optimize, height, width, num_iters)
        if key in self.model_cache:
            return self.model_cache[key]

        print('building model...')
        if no_planning:
            model = NoPlanningModel(
                dim, gamma, query_size, discretization_const,
                true_reward_space_size, num_unknown, beta, beta_planner,
                'entropy', lr, discrete, optimize)
        elif mdp.type == 'bandits':
            print 'Calling BanditsModel'
            model = BanditsModel(
                dim, gamma, query_size, discretization_const,
                true_reward_space_size, num_unknown, beta, beta_planner,
                'entropy', lr, discrete, optimize)
        elif mdp.type == 'gridworld':
            model = GridworldModel(
                dim, gamma, query_size, discretization_const,
                true_reward_space_size, num_unknown, beta, beta_planner,
                'entropy', lr, discrete, optimize, mdp.height, mdp.width,
                num_iters)
        else:
            raise ValueError('Unknown model type: ' + str(mdp.type))

        self.model_cache[key] = model
        print 'Model built and cached!'
        return model


    def find_random_query(self, query_size):
        query = [choice(self.reward_space_proxy) for _ in range(query_size)]
        # exp_regret = self.get_exp_regret_from_query([])
        return query, None, None
    
    # @profile
    def get_exp_exp_post_regret(self, query, total_reward=False):
        """Returns the expected regret after getting query answered. This measure should be minimized over queries.
        The calculation is done by calculating the probability of each answer and then the regret conditioned on it."""

        if len(query) == 0:
            return self.get_exp_regret_from_prior()

        posterior, post_averages, probs_proxy_choice, _ = self.inference.calc_posterior(query)
        avg_reward_matrix = self.inference.get_avg_reward_for_post_averages(post_averages)
        if total_reward:    # Optimizes total reward instead of regret
            regrets = -avg_reward_matrix
        else:
            optimal_rewards = self.inference.true_reward_avg_reward_vec
            regrets = optimal_rewards.reshape(1,-1) - avg_reward_matrix

        exp_regrets = np.dot(regrets * posterior, np.ones(posterior.shape[1]))  # Make sure there's no broadcasting
        exp_exp_regret = np.dot(probs_proxy_choice, exp_regrets)

        return exp_exp_regret

    def get_conditional_entropy(self, query):
        posteriors, conditional_entropy, probs_proxy_choice, _ = self.inference.calc_posterior(query, get_entropy=True)
        return conditional_entropy

    # @profile
    def get_exp_regret_from_prior(self):
        """Returns the expected regret from the prior."""
        # inference has to have cached the posterior for the right proxy & query here.
        exp_regret = 0
        prior_avg = sum([self.inference.get_prior(true_reward) * true_reward
                         for true_reward in self.inference.reward_space_true])
        for true_reward in self.inference.reward_space_true:
            p_true_reward = self.inference.get_prior(true_reward)
            optimal_reward = self.inference.get_avg_reward(true_reward,true_reward)
            prior_reward = self.inference.get_avg_reward(prior_avg, true_reward)
            regret = optimal_reward - prior_reward
            exp_regret += regret * p_true_reward
        return exp_regret

    # @profile
    def get_regret(self, proxy, true_reward):
        """Gets difference of reward under true_reward-function for optimizing for true_reward vs proxy."""
        optimal_reward = self.inference.get_avg_reward(true_reward, true_reward)
        proxy_reward = self.inference.get_avg_reward(proxy, true_reward)
        regret = optimal_reward - proxy_reward
        return regret

    # @profile
    def get_exp_regret_from_query(self, query):
        """Calculates the actual regret from a query by looping through (and weighting) true rewards."""
        if len(query) == 0:
            prior_avg = np.array(sum([self.inference.get_prior(true_reward) * true_reward
                                      for true_reward in self.inference.reward_space_true]))
            regret_vec = np.array([self.get_regret(prior_avg, true_reward) for true_reward in self.inference.reward_space_true])
            exp_regret = np.dot(regret_vec, self.inference.prior)
            return exp_regret
        else:
            raise NotImplementedError

    # @profile
    def get_regret_from_query_and_true_reward(self, query, true_reward):
        """Calculates the regret given the current prior. Only implemented for query lenget zero."""
        if len(query) == 0:
            prior_avg = self.inference.get_prior_avg()
            regret = self.get_regret(prior_avg, true_reward)
            return regret
        else:
            raise NotImplementedError






class Experiment(object):
    """"""
    def __init__(self, true_rewards, reward_space_proxy, query_size, num_queries_max, args, choosers, SEED, exp_params,
                 train_inferences, test_inferences, prior_avg):
        self.reward_space_proxy = reward_space_proxy
        self.query_size = query_size
        self.num_queries_max = num_queries_max
        self.choosers = choosers
        self.seed = SEED
        self.t_0 = time.clock()
        self.query_chooser = Query_Chooser_Subclass(reward_space_proxy, num_queries_max, args, t_0=self.t_0)
        self.results = {}
        # Add variance
        self.measures = ['true_entropy','test_regret','norm post_avg-true','post_regret','perf_measure']
        self.cum_measures = ['cum_test_regret', 'cum_post_regret']
        curr_time = str(datetime.datetime.now())[:-6]
        self.folder_name = curr_time + '-' + '-'.join([key+'='+str(val) for key, val in sorted(exp_params.items())])
        self.train_inferences = train_inferences
        self.test_inferences = test_inferences
        self.true_rewards = true_rewards
        self.prior_avg = prior_avg


    # @profile
    def get_experiment_stats(self, num_iter, num_experiments):
        self.results = {}
        post_exp_regret_measurements = []; post_regret_measurements = []
        for exp_num in range(num_experiments):
            self.run_experiment(num_iter, exp_num, num_experiments)
            self.write_experiment_results_to_csv(exp_num, num_iter)

        self.write_mean_and_median_results_to_csv(num_experiments, num_iter)

        return self.results

    # @profile
    def run_experiment(self, num_iter, exp_num, num_experiments):
        print "======================================================Experiment {n}/{N}===============================================================".format(n=exp_num + 1, N=num_experiments)
        # Initialize variables

        # Set run parameters
        inference = self.train_inferences[exp_num]
        self.query_chooser.inference = inference
        seed(self.seed)
        self.seed += 1
        'Note: true reward no longer in true reward space'
        true_reward = self.true_rewards[exp_num]
        self.results['true_reward', exp_num] = true_reward

        # Cache feature_exps and lhoods
        # print 'NOT CACHING FEATURES!'
        if any(chooser in self.choosers for chooser in ['greedy_entropy_discrete_tf','exhaustive_entropy','random','full']):
            print('caching likelihoods. Total experiment time: {t}'.format(t=time.clock()-self.t_0))
            self.query_chooser.cache_feature_expectations(self.query_chooser.reward_space_proxy)
            inference.cache_lhoods() # Only run this if the environment isn't changed each iteration
            print('done caching likelihoods. Total experiment time: {t}'.format(t=time.clock()-self.t_0))



        # Run experiment for each query chooser
        for chooser in self.choosers:
            print "===========================Experiment {n}/{N} for {chooser}===========================".format(chooser=chooser,n=exp_num+1,N=num_experiments)
            inference.reset_prior()

            for i in range(-1,num_iter):
                iter_start_time = time.clock()
                print "==========Iteration: {i}/{m} ({c}). Total time: {t}==========".format(i=i+1,m=num_iter,c=chooser,t=iter_start_time-self.t_0)
                if i > -1:
                    # Do iteration for feature-based choosers:
                    if chooser in ['feature_entropy']:
                        query, exp_post_entropy, true_log_posterior, post_avg = self.query_chooser.find_query(self.query_size, chooser, true_reward)
                        inference.update_prior(None, None, true_log_posterior)
                    else:
                        # Cache feature expectations and likelihoods
                        # # TODO: Automatically move these outside the loop if the env isn't changing
                        # self.query_chooser.cache_feature_expectations(self.query_chooser.reward_space_proxy)
                        # inference.cache_lhoods()

                        # Find best query
                        print('Finding best query. Total experiment time: {t}'.format(t=time.clock()-self.t_0))
                        query, perf_measure, true_log_posterior, true_entropy, post_avg \
                            = self.query_chooser.find_query(self.query_size, chooser, true_reward)
                        print('Found best query. Total experiment time: {t}'.format(t=time.clock()-self.t_0))
                        query = [np.array(proxy) for proxy in query]

                        # Update posterior
                        inference.update_prior(None, None, true_log_posterior)
                # Log outcomes before 1st query
                else:
                    query = None
                    true_entropy = np.log(len(inference.prior))
                    perf_measure = float('inf')
                    post_avg = self.prior_avg


                # Outcome measures
                iter_end_time = time.clock()
                duration = iter_end_time - iter_start_time
                # post_exp_regret = self.query_chooser.get_exp_regret_from_query(query=[])
                post_regret = self.query_chooser.get_regret(post_avg, true_reward) # TODO: Still plans with Python. May use wrong gamma, or trajectory normalization?
                norm_to_true = self.get_normalized_reward_diff(post_avg, true_reward)
                test_regret = self.compute_test_regret(post_avg, true_reward)
                print('Test regret: '+str(test_regret)+' | Post regret: '+str(post_regret))

                # Save results
                # self.results[chooser, 'post_exp_regret', i, exp_num],\
                self.results[chooser, 'true_entropy', i, exp_num], \
                self.results[chooser,'perf_measure', i, exp_num], \
                self.results[chooser, 'post_regret', i, exp_num], \
                self.results[chooser, 'test_regret', i, exp_num], \
                self.results[chooser, 'norm post_avg-true', i, exp_num], \
                self.results[chooser, 'query', i, exp_num], \
                self.results[chooser, 'time', i, exp_num] \
                    = true_entropy, perf_measure, post_regret, test_regret, norm_to_true, query, duration


    def compute_test_regret(self, post_avg, true_reward):
        """Computes regret from optimizing post_avg across some cached test environments."""

        regrets = np.empty(len(self.test_inferences))
        # Have to use the test environment model!
        for i, test_inference in enumerate(self.test_inferences):
            # New method using TF:
            test_mdp = test_inference.mdp
            planning_model = self.query_chooser.get_model(1)

            [post_avg_feature_exps] = planning_model.compute(['feature_exps'], self.query_chooser.sess, test_mdp, [list(post_avg)])
            [true_reward_feature_exps] = planning_model.compute(['feature_exps'], self.query_chooser.sess, test_mdp, [list(true_reward)])

            optimal_reward = np.dot(true_reward_feature_exps, true_reward)
            test_reward = np.dot(post_avg_feature_exps, true_reward)
            regret = optimal_reward - test_reward
            regrets[i] = regret

            # Old method (using normalized feature exps in Python)
            # test_reward = test_inference.get_avg_reward(post_avg, true_reward)
            # optimal_reward = test_inference.get_avg_reward(true_reward, true_reward)
            # regret = optimal_reward - test_reward
            # regrets[i] = regret
            if regret < -1:
                print 'Negative regret !!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!'
                print 'regret: ' +str(regret)
        return regrets.mean()   # Check variance here and adjust number of envs

    def get_normalized_reward_diff(self, post_avg, true_reward):
        norm_post_avg = (post_avg - post_avg.mean())
        norm_post_avg = norm_post_avg / np.linalg.norm(norm_post_avg, ord=2)
        norm_true = (true_reward - true_reward.mean())
        norm_true = norm_true / np.linalg.norm(norm_true, ord=2)

        return np.linalg.norm(norm_post_avg - norm_true)


# # @profile
    # def test_post_avg(self, post_avg, true_reward):
    #     # dist_scale = 0.5
    #     # gamma = 0.8
    #     # goals = [(1, 1), (2, 6), (3, 3), (3, 4), (4, 5), (6, 4), (6, 6)]
    #     goals = [(1, 5), (1, 2), (3, 6), (2, 3), (6, 1), (3, 5), (4, 2)]
    #     num_traject = 1
    #     # beta = 2.
    #     reps = 4
    #     post_reward_avg = 0
    #     post_regret_avg = 0
    #
    #
    #     # print true_reward
    #     # print post_avg
    #     # print true_reward - post_avg
    #
    #     # TODO: Randomize goal positions for repetitions
    #     # TODO: Why not pass on full posterior?
    #
    #     for _ in range(reps):
    #         # Set environment and agent
    #         grid = GridworldMdp.generate_random(8, 8, 0.1, len(goals), goals, living_reward=-0.01)
    #         mdp = GridworldMdpWithDistanceFeatures(grid, dist_scale, living_reward=-0.01, noise=0, rewards=post_avg)
    #         agent = OptimalAgent(gamma, num_iters=50)
    #
    #         # Set up inference
    #         env = GridworldEnvironment(mdp)
    #         inference = Inference(
    #             agent, mdp, env, beta, self.inference.reward_space_true,
    #             self.inference.reward_space_proxy, num_traject=num_traject,
    #             prior=None)
    #
    #         post_reward = inference.get_avg_reward(post_avg, true_reward)
    #         optimal_reward = inference.get_avg_reward(true_reward, true_reward)
    #         regret = optimal_reward - post_reward
    #         post_reward_avg += 1/float(reps) * post_reward
    #         post_regret_avg += 1/float(reps) * regret
    #
    #     return post_regret_avg


    def write_experiment_results_to_csv(self, exp_num, num_iter):
        """Writes a CSV for every chooser for every experiment. The CSV's columns are 'iteration' and all measures in
        self.measures."""
        if not os.path.exists('data/'+self.folder_name):
            os.mkdir('data/'+self.folder_name)
        else:
            Warning('Existing experiment stats overwritten')
        for chooser in self.choosers:
            f = open('data/'+self.folder_name+'/'+chooser+str(exp_num)+'.csv','w')  # Open CSV in folder with name exp_params
            writer = csv.DictWriter(f, fieldnames=['iteration']+self.measures+self.cum_measures+['time'])
            writer.writeheader()
            rows = []
            cum_test_regret, cum_post_regret = 0, 0
            for i in range(-1,num_iter):
                csvdict = {}
                csvdict['iteration'] = i
                for measure in self.measures + ['time']:
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
        self.measures + self.cum_measures + ['time']."""
        if not os.path.exists('data/' + self.folder_name):
            os.mkdir('data/' + self.folder_name)
        else:
            Warning('Existing experiment stats overwritten')

        f_mean_all = open('data/'+self.folder_name+'/'+'all choosers'+'-means-'+'.csv','w')
        writer_mean_all_choosers = csv.DictWriter(f_mean_all, fieldnames=['iteration']+self.measures+self.cum_measures+['time'])

        f_median_all = open('data/'+self.folder_name+'/'+'all choosers'+'-medians-'+'.csv','w')
        writer_medians_all_choosers = csv.DictWriter(f_median_all, fieldnames=['iteration']+self.measures+self.cum_measures+['time'])

        f_sterr_all = open('data/'+self.folder_name+'/'+'all choosers'+'-sterr-'+'.csv','w')
        writer_sterr_all_choosers = csv.DictWriter(f_sterr_all, fieldnames=['iteration']+self.measures+self.cum_measures+['time'])

        for chooser in self.choosers:
            f_mean = open('data/'+self.folder_name+'/'+chooser+'-means-'+'.csv','w')
            f_median = open('data/'+self.folder_name+'/'+chooser+'-medians-'+'.csv','w')
            f_sterr = open('data/'+self.folder_name+'/'+chooser+'-sterr-'+'.csv','w')

            writer_mean = csv.DictWriter(f_mean, fieldnames=['iteration']+self.measures+self.cum_measures+['time'])
            writer_median = csv.DictWriter(f_median, fieldnames=['iteration']+self.measures+self.cum_measures+['time'])
            writer_sterr = csv.DictWriter(f_sterr, fieldnames=['iteration']+self.measures+self.cum_measures+['time'])

            writer_mean.writeheader()
            writer_median.writeheader()
            writer_sterr.writeheader()
            rows_mean = []
            rows_median = []
            rows_sterr = []
            cum_test_regret = np.zeros(num_experiments)
            cum_post_regret = np.zeros(num_experiments)

            for i in range(-1,num_iter):
                csvdict_mean = {}
                csvdict_median = {}
                csvdict_sterr = {}

                csvdict_mean['iteration'] = i
                csvdict_median['iteration'] = i
                csvdict_sterr['iteration'] = i

                for measure in self.measures + ['time']:
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
