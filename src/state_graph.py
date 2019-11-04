#!/usr/bin/env python3

import sys
from random import randrange
from pprint import pformat
from graphviz import Digraph

class LossyStateGraph:

    def __init__(self, capacity, window_size):
        self.graph = [None] * capacity
        self.capacity = capacity
        self.is_stable = False

        self.drifted_tree_counter = 0
        self.window_size = window_size

        # self.g = Digraph('G', filename='state_transition', engine='sfdp', format='svg')

    def get_next_tree_id(self, src):
        cur_node = self.graph[src]
        if not cur_node or cur_node.total_weight == 0:
            return -1

        r = randrange(cur_node.total_weight)
        cur_sum = 0

        for key, val in cur_node.neighbors.items():
            cur_sum += val[0]
            if r < cur_sum:
                val[1] += 1
                return key

        return -1

    def update(self, warning_tree_count):
        self.drifted_tree_counter += warning_tree_count
        if self.drifted_tree_counter < self.window_size:
            return

        self.drifted_tree_counter -= self.window_size

        # lossy count
        for node in self.graph:
            if node is None:
                continue

            for nei_key, val in list(node.neighbors.items()):
                # increment freq by #hits
                val[0] += val[1]
                node.total_weight += val[1]

                # reset #hits
                val[1] = 0

                # decrement freq by 1
                val[0] -= 1
                node.total_weight -= 1

                if val[0] <= 0:
                    # remove edge
                    self.graph[nei_key].indegree -= 1
                    self.__try_remove_node(nei_key)

                    del node.neighbors[nei_key]

            self.__try_remove_node(node.key)

    def __try_remove_node(self, key):
        node = self.graph[key]

        if node.indegree == 0 and len(node.neighbors) == 0:
            self.graph[key] = None

    def add_node(self, key):
        self.graph[key] = Node(key)

    def add_edge(self, src, dest):
        if self.graph[src] == None:
            self.add_node(src)
        if self.graph[dest] == None:
            self.add_node(dest)

        src_node = self.graph[src]

        if dest not in src_node.neighbors.keys():
            src_node.neighbors[dest] = [0, 0]
            self.graph[dest].indegree += 1

        # update #hits
        src_node.neighbors[dest][1] += 1

        # self.g.edge(str(src), str(dest), label=str(src_node.neighbors[dest][0]))
        # self.g.render(view=False)

    def get_size(self):
        size = 0

        for node in self.graph:
            if not node:
                continue
            size += node.get_size()
        return size

    def __str__(self):
        strs = []
        for i in range(0, self.capacity):
            if self.graph[i] == None:
                continue
            strs.append(f"Node {i}, total_weight={self.graph[i].total_weight}")
            strs.append(pformat(self.graph[i].neighbors))

        return '\n'.join(strs)

    def __repr__(self):
        return self.__str__()

class Node:
    def __init__(self, key):
        self.key = key
        self.neighbors = dict() # <tree_id, [weight, num_hit]>
        self.indegree = 0
        self.total_weight = 0

    def get_size(self):
        return sys.getsizeof(self.neighbors)
