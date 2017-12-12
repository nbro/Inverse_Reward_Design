from agents import DirectionalAgent, ImmediateRewardAgent
from gridworld import GridworldMdp, GridworldEnvironment, Direction, NStateMdp


def run_agent(agent, env, episode_length=float("inf")):
    """Runs the agent on the environment for one episode.

    The agent will keep being asked for actions until the environment says the
    episode is over, or once the episode_length has been reached.

    agent: An Agent (which in particular has get_action and inform_minibatch).
    env: An Environment in which the agent will act.
    episode_length: The maximum number of actions that the agent can take. If
    the agent has not reached a terminal state by this point, the episode is
    terminated early.

    Returns the trajectory that the agent took, which is a list of (s, a, s', r)
    tuples.
    """
    env.reset()
    trajectory = []
    # Note: Trajectory will include terminal state iff episode length not reached. Then the final next_state won't be rewarded.
    while len(trajectory) < episode_length and not env.is_done():
        curr_state = env.get_current_state()
        action = agent.get_action(curr_state)
        next_state, reward = env.perform_action(action)
        minibatch = (curr_state, action, next_state, reward)
        agent.inform_minibatch(*minibatch)
        trajectory.append(minibatch)
    return trajectory


if __name__=='__main__':
    rewards = [0, 1, 2, 3, 4]
    mdp = NStateMdp(num_states=5, rewards=rewards, start_state=0, preterminal_states=[3])
    env = GridworldEnvironment(mdp)
    default_action = 1
    # agent = DirectionalAgent(default_action)
    agent = ImmediateRewardAgent()
    agent.set_mdp(mdp)
    print(run_agent(agent, env, episode_length=float(6)))
