import numpy as np
import random
from collections import namedtuple, deque

from model import Critic, Actor
import torch
from torch import autograd
from torch import nn
import torch.nn.functional as F
import torch.optim as optim
import random_p as rm
from schedule import LinearSchedule

BUFFER_SIZE = int(1e6)  # replay buffer size
BATCH_SIZE = 256         # minibatch size
GAMMA = 0.99            # discount factor
TAU = 1e-3              # for soft update of target parameters
ACTOR_LR = 1e-3         # Actor network learning rate 
CRITIC_LR = 1e-4        # Actor network learning rate
UPDATE_EVERY = 20       # how often to update the network (time step)
UPDATE_TIMES = 10       # how many times to update in one go

device = torch.device("cuda:0" if torch.cuda.is_available() else "cpu")

class Agent():
    """Interacts with and learns from the environment."""

    def __init__(self, state_size, action_size, num_agents,seed,fc1=400,fc2=300):
        """Initialize an Agent object.
        
        Params
        ======
            state_size (int): dimension of each state
            action_size (int): dimension of each action
            seed (int): random seed
        """
        self.state_size = state_size
        self.action_size = action_size
        self.seed = random.seed(seed)
        self.num_agents=num_agents
        
        self.noise=[OrnsteinUhlenbeckProcess(size=(action_size, ), std=0.2) for i in range(num_agents)]

        # actor local and target network (Policy gradient)
        self.actor_local = Actor(state_size, action_size, fc1, fc2, seed).to(device)
        self.actor_target = Actor(state_size, action_size, fc1, fc2, seed).to(device)

        # critic local and target network (Q-Learning)
        self.critic_local = Critic(state_size, action_size, fc1, fc2, seed).to(device)
        self.critic_target = Critic(state_size, action_size, fc1, fc2, seed).to(device)
        
        # optimizer for critic and actor network
        self.actor_optimizer = optim.Adam(self.actor_local.parameters(), lr=ACTOR_LR)
        self.critic_optimizer = optim.Adam(self.critic_local.parameters(), lr=CRITIC_LR)

        # Replay memory
        self.memory = ReplayBuffer(action_size, BUFFER_SIZE, BATCH_SIZE, seed)
        
        # Initialize time step (for updating every UPDATE_EVERY steps)
        self.t_step = 0
    
    def step(self, state, action, reward, next_state, done):
        # Save experience in replay memory
        for i in range(self.num_agents):
            self.memory.add(state[i], action[i], reward[i], next_state[i], done[i])
        
        self.t_step += 1
            
        # If enough samples are available in memory, get random subset and learn
        if len(self.memory) > BATCH_SIZE:
            if self.t_step % UPDATE_EVERY == 0:
                for i in range(UPDATE_TIMES):
                    experiences = self.memory.sample()
                    self.learn(experiences, GAMMA)

    def act(self, state,training=True):
        """Returns continous actions values for all action for given state as per current policy.
        
        Params
        ======
            state (array_like): current state
        """
        
        state = torch.from_numpy(state).float().detach().to(device)
        
        self.actor_local.eval()
        with torch.no_grad():
            actions=self.actor_local(state).cpu().data.numpy()
        self.actor_local.train()
        
        noise = np.array([self.noise[i].sample() for i in range(self.num_agents)])
        
        return np.clip(actions+noise,-1,1)

    def learn(self, experiences, gamma):
        """Update policy and value parameters using given batch of experience tuples.
        Q_targets = r + γ * critic_target(next_state, actor_target(next_state))
        where:
            actor_target(state) -> action
            critic_target(state, action) -> Q-value
        Params
        ======
            experiences (Tuple[torch.Tensor]): tuple of (s, a, r, s', done) tuples 
            gamma (float): discount factor
        """
        
        states, actions, rewards, next_states, dones = experiences

        # ---------------------------- update critic ---------------------------- #
        # Get predicted next-state actions and Q values from target models
        actions_next = self.actor_target(next_states)
        Q_targets_next = self.critic_target(next_states, actions_next)
        # Compute Q targets for current states (y_i)
        Q_targets = rewards + (gamma * Q_targets_next * (1 - dones))
        # Compute critic loss
        Q_expected = self.critic_local(states, actions)
        critic_loss = F.mse_loss(Q_expected, Q_targets)
        # Minimize the loss
        self.critic_optimizer.zero_grad()
        critic_loss.backward()
        torch.nn.utils.clip_grad_norm_(self.critic_local.parameters(), 1)
        self.critic_optimizer.step()

        # ---------------------------- update actor ---------------------------- #
        # Compute actor loss
        actions_pred = self.actor_local(states)
        actor_loss = -self.critic_local(states, actions_pred).mean()
        # Minimize the loss
        self.actor_optimizer.zero_grad()
        torch.nn.utils.clip_grad_norm_(self.actor_local.parameters(), 1)
        actor_loss.backward()
        self.actor_optimizer.step()

        # ----------------------- update target networks ----------------------- #
        self.soft_update(self.critic_local, self.critic_target, TAU)
        self.soft_update(self.actor_local, self.actor_target, TAU)                     

    def soft_update(self, local_model, target_model, tau):
        """Soft update model parameters.
        θ_target = τ*θ_local + (1 - τ)*θ_target

        Params
        ======
            local_model (PyTorch model): weights will be copied from
            target_model (PyTorch model): weights will be copied to
            tau (float): interpolation parameter 
        """
        for target_param, local_param in zip(target_model.parameters(), local_model.parameters()):
            target_param.data.copy_(tau*local_param.data + (1.0-tau)*target_param.data)
            
    def reset_random(self):
        for i in range(self.num_agents):
            self.noise[i].reset_states()

#code from Shangtong Zhang(zhangshangtong.cpp@gmail.com)
class OrnsteinUhlenbeckProcess:
    def __init__(self, size, std, theta=.15, dt=1e-2, x0=None):
        self.theta = theta
        self.mu = 0
        self.std = std
        self.dt = dt
        self.x0 = x0
        self.size = size
        self.reset_states()

    def sample(self):
        x = self.x_prev + self.theta * (self.mu - self.x_prev) * self.dt + self.std * np.sqrt(self.dt) * np.random.randn(*self.size)
        self.x_prev = x
        return x

    def reset_states(self):
        self.x_prev = self.x0 if self.x0 is not None else np.zeros(self.size)

class ReplayBuffer:
    """Fixed-size buffer to store experience tuples."""

    def __init__(self, action_size, buffer_size, batch_size, seed):
        """Initialize a ReplayBuffer object.

        Params
        ======
            action_size (int): dimension of each action
            buffer_size (int): maximum size of buffer
            batch_size (int): size of each training batch
            seed (int): random seed
        """
        self.action_size = action_size
        self.memory = deque(maxlen=buffer_size)  
        self.batch_size = batch_size
        self.experience = namedtuple("Experience", field_names=["state", "action", "reward", "next_state", "done"])
        self.seed = random.seed(seed)
    
    def add(self, state, action, reward, next_state, done):
        """Add a new experience to memory."""
        e = self.experience(state, action, reward, next_state, done)
        self.memory.append(e)
    
    def sample(self):
        """Randomly sample a batch of experiences from memory."""
        experiences = random.sample(self.memory, k=self.batch_size)

        states = torch.from_numpy(np.vstack([e.state for e in experiences if e is not None])).float().to(device)
        actions = torch.from_numpy(np.vstack([e.action for e in experiences if e is not None])).float().to(device)
        rewards = torch.from_numpy(np.vstack([e.reward for e in experiences if e is not None])).float().to(device)
        next_states = torch.from_numpy(np.vstack([e.next_state for e in experiences if e is not None])).float().to(device)
        dones = torch.from_numpy(np.vstack([e.done for e in experiences if e is not None]).astype(np.uint8)).float().to(device)
  
        return (states, actions, rewards, next_states, dones)

    def __len__(self):
        """Return the current size of internal memory."""
        return len(self.memory)