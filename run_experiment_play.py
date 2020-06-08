# changed by sarahgillet, June 2020 to allow for online play on Hanabi.live
# coding=utf-8
# Copyright 2018 The Dopamine Authors and Google LLC.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#
#
#
# This file is a fork of the original Dopamine code incorporating changes for
# the multiplayer setting and the Hanabi Learning Environment.
#
"""Run methods for training a DQN agent on Atari.

Methods in this module are usually referenced by |train.py|.
"""

from __future__ import absolute_import
from __future__ import division
from __future__ import print_function


from hanabi_learning_environment.agents.rainbow.run_experiment import ObservationStacker
from pathlib import Path


import time

from hanabi_learning_environment.agents.rainbow.third_party.dopamine import checkpointer
from hanabi_learning_environment.agents.rainbow.third_party.dopamine import iteration_statistics
#import dqn_agent
import gin.tf
from hanabi_learning_environment import rl_env
import numpy as np
from hanabi_learning_environment.agents.rainbow import rainbow_agent
from hanabi_learning_environment.agents.rainbow import dqn_agent
import tensorflow as tf

from hanabi_live_bot.hanabi_client import HanabiClient
from hanabi_live_bot.connection import establishConnection
LENIENT_SCORE = False

# to get the environment file for agent login


def load_gin_configs(gin_files, gin_bindings):
    """Loads gin configuration files.

    Args:
      gin_files: A list of paths to the gin configuration files for this
        experiment.
      gin_bindings: List of gin parameter bindings to override the values in the
        config files.
    """
    gin.parse_config_files_and_bindings(gin_files,
                                        bindings=gin_bindings,
                                        skip_unknown=False)


class HanabiLiveRainbowAgent(HanabiClient):
    def __init__(self, agent, environment, obs_stacker, url, cookie):
        HanabiClient.__init__(self, url, cookie)
        self.agent = agent
        self.environment = environment
        self.obs_stacker = obs_stacker
        self.obs_stacker.reset_stack()
        self.max_pile = {1: 3, 2: 2, 3: 2, 4: 2, 5: 1}
        self.actionEncoding = {'play': 0, 'discard': 1, 'strike': 0, 'clue': 2}

    def GetMoveUid(self, table_id, move_type, card_index, suit, rank):
        target_offset = 1
        state = self.games[table_id]
        if move_type == 1:
            return card_index
        elif move_type == 0:
            return len(state.hands[state.our_index]) + card_index
        elif move_type == 2:
            return 5 + 5 + (target_offset - 1) * 5 + suit
        elif move_type == 3:
            return 5+5 + 5 + (target_offset - 1) * 5 + rank
        else:
            return -1

    # def run_one_episode(self, agent, environment, obs_stacker):
    def extractCurrentObservationAndLegalActions(self, table_id):
        # build directly vectorized form of observation from game state
        state = self.games[table_id]
        vectorizedObs = [0]*658
        currOffset = 0
        # build card vector, only one opponent, pick values of other player
        handOfOtherPlayer = state.hands[(state.our_index+1) % 2]
        for item in handOfOtherPlayer:
            offsetCard = self.findCardIndex(
                handOfOtherPlayer, item['order'])*10
            if offsetCard < 0:
                print('error: unable to find card with order ' + str(order) + ' in'
                      'the hand of player ' + str(seat))
                return None
            offsetSuit = item['suit']
            # 0: Red, 1:Yellow ,2: Green, 3: Blue, 4: Purple
            offsetRank = item['rank']-1
            vectorizedObs[offsetCard+offsetSuit*5+offsetRank] = 1
            currOffset += 5*5
        # bit that tells if hand is full or not (1 = not full)
        vectorizedObs[currOffset] = 0 if len(
            state.hands[state.our_index]) == 5 else 1
        vectorizedObs[currOffset +
                      1] = 0 if len(state.hands[(state.our_index+1) % 2]) == 5 else 1
        currOffset += 2
        # fill remaining deck size as thermometer (as many 1's as cards)
        vectorizedObs[currOffset:currOffset +
                      state.num_cards_deck] = [1]*state.num_cards_deck
        currOffset += 40
        # fill fireworks (cards placed correctly)
        for i in range(len(state.play_stacks)):
            if len(state.play_stacks[i]) > 0:
                offsetStack = currOffset+5*i
                vectorizedObs[offsetStack:offsetStack +
                              len(state.play_stacks[i])] = [1]*len(state.play_stacks[i])
        currOffset += 25  # 25 bits for encoding stack of cards
        # fill information tokens aka clues 8 in thermometer style
        vectorizedObs[currOffset:currOffset +
                      state.clue_tokens] = [1]*state.clue_tokens
        currOffset += 8  # max num of tokens
        # fill in remaining life tokens
        vectorizedObs[currOffset:currOffset +
                      state.life_tokens] = [1]*state.life_tokens
        currOffset += 3
        # encode discard stack
        # for each color
        # // 3 cards of lowest rank (1), 1 card of highest rank (5), 2 of all else. So each color would be
        #  ordered like so:
        #  LLL      H
        #   1100011101
        # enconding means: two low ones are on the pile, the highest, one 4 and both 3
        for suit in range(5):
            for rank in range(1, 6):
                vectorizedObs[currOffset:currOffset+len(state.discard_pile[suit][rank])] = [
                    1] * len(state.discard_pile[suit][rank])
                currOffset += self.max_pile[rank]

        # for action encoding enum Type { kPlay, kDiscard, kRevealColor, kRevealRank };
        # set index of player that played last action
        index_last_player = 0
        if state.turn > 0:
            if (state.last_action['who'] != state.our_index):
                index_last_player = 1
            vectorizedObs[currOffset+index_last_player] = 1
        currOffset += 2
        # encode action
        actionCode = -1
        if state.turn > 0:
            actionCode = self.actionEncoding[state.last_action['type']]
            if (actionCode == 2):  # clue action needs further refinement
                actionCode += state.last_action['clue']['type']
            vectorizedObs[currOffset+actionCode] = 1
        currOffset += 4
        # reveal action, encode target player in that case (one-hot)
        if actionCode >= 2:
            if state.last_action['target'] == state.our_index:
                vectorizedObs[currOffset] = 1
            else:
                vectorizedObs[currOffset+1] = 1
        currOffset += 2
        # in case of color clue, encode color
        if actionCode == 2:
            vectorizedObs[currOffset+state.last_action['clue']['value']] = 1
        currOffset += 5
        # in case of rank clue, encode rank
        if actionCode == 3:
            vectorizedObs[currOffset+state.last_action['clue']['value']] = 1
        currOffset += 5
        # encode reveal outcome, which cards on the hand were hinted
        if actionCode >= 2:
            listTargetClue = state.last_action['list']
            hand = state.hands[state.last_action['target']]
            for clueTarget in listTargetClue:
                card_index = super().findCardIndex(hand, clueTarget)
                if card_index != -1:
                    vectorizedObs[currOffset+card_index] = 1
                else:
                    print('error: unable to find card with order ' + str(order) + ' in'
                          'the hand of player ' + str(seat))
        currOffset += 5
        # encode played/discarded card in case action was play/discard
        card = None
        if actionCode == 0 or actionCode == 1:
            card_index = -1
            if state.last_action['type'] != 'play':
                # find card on discard pile
                searchForOrder = -1
                if actionCode == 0:
                    searchForOrder = state.last_action['order']
                else:
                    searchForOrder = state.last_action['which']['order']
                for suit in state.discard_pile:
                    for rank in suit:
                        for listItem in suit[rank]:
                            if listItem['order'] == searchForOrder:
                                card = listItem
                                break
                    # cardOrder = state.last_action['which']['order']
                    # handSeat = state.last_action['which']['index']
                card_index = card['hand_index']
            else:
                # find card on play_stacks pile
                cardOrder = state.last_action['which']['order']
                for stacks in state.play_stacks:
                    for cards in stacks:
                        if cards['order'] == cardOrder:
                            card_index = cards['hand_index']
                        if card_index != -1:
                            break
            if card_index != -1:
                vectorizedObs[currOffset+card_index] = 1
            else:
                print('error: unable to find card with order line 537')
        currOffset += 5
        # encode card
        if (actionCode == 0 or actionCode == 1) and card is not None:
            # card_index = -1
            # if state.last_action['type'] != 'strike':
            #     offsetSuit = state.last_action['which']['suit']
            #     offsetRank = state.last_action['which']['rank']
            #     vectorizedObs[currOffset+offsetSuit*5+offsetRank]=1
            # else:
            #     # find card on discard pile
            #     for suit in state.discard_pile:
            #         for rank in suit:
            #             for listItem in suit[rank]:
            #                 if listItem['order'] == state.last_action['order']:
            #                     offsetSuit = listItem['suit']
            #                     offsetRank = listItem['rank']
            #                     vectorizedObs[currOffset+offsetSuit*5+offsetRank]=1
            offsetSuit = card['suit']
            offsetRank = card['rank']
            vectorizedObs[currOffset+offsetSuit*5+offsetRank] = 1
        currOffset += 25
        if actionCode == 0 and state.last_action['type'] != 'strike':
            vectorizedObs[currOffset] = 1
        if actionCode == 1:
            vectorizedObs[currOffset+1] = 1
        currOffset += 2
        # encode clue knowledge
        listHandsOurOrder = [state.hands[state.our_index],
                             state.hands[(state.our_index+1) % 2]]
        for handI in range(len(listHandsOurOrder)):
            hand = listHandsOurOrder[handI]
            for i in range(len(hand)):
                vectorizedObs[currOffset:currOffset +
                              len(hand[i]['knowledge'])] = hand[i]['knowledge']
                currOffset += len(hand[i]['knowledge'])
                vectorizedObs[currOffset:currOffset +
                              len(hand[i]['clue'][0])] = hand[i]['clue'][0]
                currOffset += len(hand[i]['clue'][0])
                vectorizedObs[currOffset:currOffset +
                              len(hand[i]['clue'][1])] = hand[i]['clue'][1]
                currOffset += len(hand[i]['clue'][1])
        print(currOffset)
        self.obs_stacker.add_observation(vectorizedObs, 0)
        observation_vector = self.obs_stacker.get_observation_stack(0)
        # legal_moves =
        self.computeLegalMoves(state)
        return observation_vector  # , legal_moves

    def computeLegalMoves(self, state):
        # MaxDiscardMoves() + MaxPlayMoves() + MaxRevealColorMoves() + MaxRevealRankMoves();
        num_actions = 5 + 5 + 5 + 5
        
        legal_move_list = []
        # play moves
        for i in range(5):
            legal_move_list.append({
                'action_type': 'play',
                'card_index': i
            })
        # discard moves
        for i in range(5):
            legal_move_list.append({
                'action_type': 'discard',
                'card_index': i
            })
        handPartner = state.hands[(state.our_index+1) % 2]
        listColors = []
        listRanks = []
        for card in handPartner:
            listColors.append(card['suit'])
            listRanks.append(card['rank'])
        setColor = set(listColors)
        setRanks = set(listRanks)
        for suit in setColor:
            legal_move_list.append({'action_type': 'REVEAL_COLOR',
                                    'color': suit,
                                    'target_offset': 1})
        for rank in setRanks:
            legal_move_list.append({'action_type': 'REVEAL_RANK',
                                    'color': rank,
                                    'target_offset': 1})
        # legal_moves TODO, find where format located
        #legal_moves = format_legal_moves(legal_moves, num_actions)

    def decide_action(self, table_id):
        self.extractCurrentObservationAndLegalActions(table_id)
        super().decide_action(table_id)


@gin.configurable
def start_experiment(agent,
                     environment,
                     start_iteration,
                     obs_stacker,
                     experiment_logger,
                     experiment_checkpointer,
                     checkpoint_dir,
                     num_iterations=200,
                     training_steps=5000,
                     logging_file_prefix='log',
                     log_every_n=10,
                     checkpoint_every_n=1):
    """Runs the agent that can connect to Hanabi-Live and play one game."""
    tf.logging.info('Beginning playing...')
    # statistics defined in run_one_iteration
    env_path = Path('.') / '.env'
    url, cookie = establishConnection(env_path)
    HanabiLiveRainbowAgent(agent, environment, obs_stacker, url, cookie).start_server()
    # for iteration in range(start_iteration, num_iterations):
    #   start_time = time.time()
    #   statistics = run_one_iteration(agent, environment, obs_stacker, iteration,
    #                                  training_steps)
    #   tf.logging.info('Iteration %d took %d seconds', iteration,
    #                   time.time() - start_time)
    #   start_time = time.time()
    #   log_experiment(experiment_logger, iteration, statistics,
    #                  logging_file_prefix, log_every_n)
    #   tf.logging.info('Logging iteration %d took %d seconds', iteration,
    #                   time.time() - start_time)
    #   start_time = time.time()
    #   checkpoint_experiment(experiment_checkpointer, agent, experiment_logger,
    #                         iteration, checkpoint_dir, checkpoint_every_n)
    #   tf.logging.info('Checkpointing iteration %d took %d seconds', iteration,
    #                   time.time() - start_time)
