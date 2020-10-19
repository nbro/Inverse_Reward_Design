from subprocess import call

# Discrete experiments

NUM_EXPERIMENTS = '100'  # Modify this to change the sample size

discr_query_sizes = ['2', '3', '5', '10']
choosers_continuous = ['feature_entropy_search_then_optim', 'feature_random',
                       'feature_entropy_random_init_none']  # 'feature_entropy_init_none', 'feature_entropy_search']
choosers_discrete = ['greedy_discrete', 'random', 'exhaustive']
mdp_types = ['gridworld', 'bandits']
num_iter = {'gridworld': '20', 'bandits': '20'}
num_subsamples_full = '5000';
num_subsamples_not_full = '5000'
beta_both_mdps = '0.5'
num_q_max = '10000'
rsize = '1000000'
proxy_space_is_true_space = '0'
exp_name = '14May_reward_hacking'


def run(chooser, qsize, mdp_type, num_iter, objective='entropy', discretization_size='5', discretization_size_human='5',
        viter='15', rsize=rsize, subsampling='1', proxy_space_is_true_space='0',
        subs_full=num_subsamples_full, full_IRD_subsample_belief='no', log_objective='1',
        repeated_obj='0', num_obj_if_repeated='50', decorrelate_test_feat='1',
        dist_scale='0.2', linear_features='1', height='12', width='12',
        num_test_envs='100', beta=beta_both_mdps):
    if mdp_type == 'bandits':
        # Values range from -5 to 5 approximately, so setting beta to 1 makes
        # the worst Q-value e^10 times less likely than the best one
        beta_planner = '0.5'
        dim = '20'
        # TODO: Set the following to the right values
        lr = '20.'
        num_iters_optim = '20'
    else:
        # Values range from 50-100 when using 25 value iterations.
        beta_planner = '1'
        dim = '20'
        # TODO: Set the following to the right values
        lr = '20'
        num_iters_optim = '20'

    command = ['python', 'run_IRD.py',
               '-c', chooser,
               '--query_size', qsize,
               '--num_experiments', NUM_EXPERIMENTS,
               '--num_iter', num_iter[mdp_type],
               '--gamma', '1.',
               '--size_true_space', rsize,
               '--size_proxy_space', '100',
               '--seed', '1',
               '--beta', beta,
               '--beta_planner', beta_planner,
               '--num_states', '100',  # Only applies for bandits
               '--dist_scale', dist_scale,
               '--num_queries_max', num_q_max,
               '--height', height,  # Only applies for gridworld
               '--width', width,  # Only applies for gridworld
               '--lr', lr,
               '--num_iters_optim', num_iters_optim,
               '--value_iters', viter,
               '--mdp_type', mdp_type,
               '--feature_dim', dim,
               '--discretization_size', discretization_size,
               '--discretization_size_human', discretization_size_human,
               '--num_test_envs', num_test_envs,
               '--subsampling', subsampling,
               '--num_subsamples', subs_full if chooser == 'full' else num_subsamples_not_full,
               '--weighting', '1',
               '--well_spec', '1',
               '--linear_features', linear_features,
               '--objective', objective,
               '--log_objective', log_objective,
               '-weights_dist_init', 'normal2',
               '-weights_dist_search', 'normal2',
               '--only_optim_biggest', '1',
               '--proxy_space_is_true_space', proxy_space_is_true_space,
               '--full_IRD_subsample_belief', full_IRD_subsample_belief,
               '--exp_name', exp_name,
               '--repeated_obj', repeated_obj,
               '--num_obj_if_repeated', num_obj_if_repeated,
               '--decorrelate_test_feat', decorrelate_test_feat
               ]
    print('Running command', ' '.join(command))
    call(command)


# Run as usual
def run_discrete():
    for mdp_type in mdp_types:

        run('full', '2', mdp_type, num_iter=num_iter, proxy_space_is_true_space=proxy_space_is_true_space)

        for chooser in choosers_discrete:
            for qsize in discr_query_sizes:
                run(chooser, qsize, mdp_type, num_iter=num_iter)


def run_reward_hacking():
    mdp_type = 'gridworld'
    repeated_obj = '1'
    num_obj_if_repeated = '100'
    qsizes = ['2', '5']
    height, width = '52', '52'
    viter = str(int(int(height) * 1.5))
    beta = str(7.5 / float(viter))  # Decrease beta for higher viter. Make prop to num objects too?
    num_test_envs = '25'

    for dist_scale in ['0.1', '0.3', '1']:
        for decorrelate_test_feat in ['1', '0']:

            run('full', '2', mdp_type, num_iter=num_iter,
                repeated_obj=repeated_obj, num_obj_if_repeated=num_obj_if_repeated, dist_scale=dist_scale,
                height=height, width=width, num_test_envs=num_test_envs, viter=viter, beta=beta,
                decorrelate_test_feat=decorrelate_test_feat)

            for chooser in ['greedy_discrete', 'random']:
                for qsize in qsizes:
                    run(chooser, qsize, mdp_type, num_iter=num_iter,
                        repeated_obj=repeated_obj, num_obj_if_repeated=num_obj_if_repeated, dist_scale=dist_scale,
                        height=height, width=width, num_test_envs=num_test_envs, viter=viter, beta=beta,
                        decorrelate_test_feat=decorrelate_test_feat)


def run_full():
    for mdp_type in mdp_types:
        for num_subsamples_full in ['1000', '500', '100', '50', '10', '5', '2', '10000']:
            for full_IRD_subsample_belief in ['yes', 'uniform', 'no']:
                if full_IRD_subsample_belief == 'no':
                    run('full', '2', mdp_type, num_iter=num_iter, proxy_space_is_true_space=proxy_space_is_true_space,
                        subs_full=num_subsamples_full, full_IRD_subsample_belief=full_IRD_subsample_belief,
                        size_proxy_space=num_subsamples_full)
                run('full', '2', mdp_type, num_iter=num_iter, proxy_space_is_true_space=proxy_space_is_true_space,
                    subs_full=num_subsamples_full, full_IRD_subsample_belief=full_IRD_subsample_belief)
        # Interesting question: How high can 'uniform' go before it gets worse? (could be pretty high)
        # Test with smaller r_size if the turning point turns out >100.
        # Hypothesis: 'yes' gets monotonely better with larger sizes bc only top samples matter (but flattens out quite quickly)


def run_objectives():
    # Continuous
    # qsize = '3'
    # discretization_size = '3'
    # discretization_size_human = '5'
    # chooser = 'feature_entropy_search_then_optim'

    # Discrete
    chooser = 'greedy_discrete'
    for mdp_type in mdp_types:
        # for log_objective in ['1' , '0']:
        for qsize in discr_query_sizes:
            for objective in ['query_neg_entropy', 'entropy']:
                run(chooser, qsize, mdp_type,
                    # discretization_size=discretization_size, discretization_size_human=discretization_size_human, , log_objective=log_objective
                    num_iter=num_iter, objective=objective)


# # Run with different rsize and subsampling values
# def run_subsampling():
#     for mdp_type in mdp_types:
#         for rsize in true_reward_space_sizes:
#             if rsize == '10000':
#                 subsampling = '0'
#             else: subsampling = '1'
#
#
#             for objective in objectives:
#                 for chooser in choosers_discrete:
#                         for qsize in discr_query_sizes:
#                             run(chooser, qsize, mdp_type, objective, rsize=rsize, subsampling=subsampling)
#                 run('full', '2', mdp_type, objective, rsize=rsize, subsampling=subsampling, num_iter=num_iter)


def run_discrete_optimization():
    for mdp_type in mdp_types:
        for qsize in discr_query_sizes:
            for chooser in ['incremental_optimize', 'joint_optimize']:
                run(chooser, qsize, mdp_type)


def run_continuous():
    for mdp_type in mdp_types:
        for qsize, discretization_size, discretization_size_human in [('3', '3', '5'), ('2', '5', '9'),
                                                                      ('1', '9', '18')]:
            for chooser in choosers_continuous:
                run(chooser, qsize, mdp_type,
                    discretization_size=discretization_size,
                    discretization_size_human=discretization_size_human,
                    num_iter=num_iter)


if __name__ == '__main__':
    # run_objectives()
    run_reward_hacking()
    run_continuous()
    run_discrete()
