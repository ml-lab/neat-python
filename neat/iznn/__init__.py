"""
This module implements a spiking neural network.
Neurons are based on the model described by:
    
Izhikevich, E. M.
Simple Model of Spiking Neurons
IEEE TRANSACTIONS ON NEURAL NETWORKS, VOL. 14, NO. 6, NOVEMBER 2003

http://www.izhikevich.org/publications/spikes.pdf
"""

from neat.attributes import FloatAttribute
from neat.genes import BaseGene, DefaultGeneConfig, DefaultConnectionGene
from neat.genome import DefaultGenomeConfig, DefaultGenome
from neat.graphs import required_for_output
from neat.six_util import itervalues, iteritems

# a, b, c, d are the parameters of the Izhikevich model.
# a: the time scale of the recovery variable
# b: the sensitivity of the recovery variable
# c: the after-spike reset value of the membrane potential
# d: after-spike reset of the recovery variable
# The following parameter sets produce some known spiking behaviors:
REGULAR_SPIKING_PARAMS        = {'a': 0.02, 'b': 0.20, 'c': -65.0, 'd': 8.00}
INTRINSICALLY_BURSTING_PARAMS = {'a': 0.02, 'b': 0.20, 'c': -55.0, 'd': 4.00}
CHATTERING_PARAMS             = {'a': 0.02, 'b': 0.20, 'c': -50.0, 'd': 2.00}
FAST_SPIKING_PARAMS           = {'a': 0.10, 'b': 0.20, 'c': -65.0, 'd': 2.00}
THALAMO_CORTICAL_PARAMS       = {'a': 0.02, 'b': 0.25, 'c': -65.0, 'd': 0.05}
RESONATOR_PARAMS              = {'a': 0.10, 'b': 0.25, 'c': -65.0, 'd': 2.00}
LOW_THRESHOLD_SPIKING_PARAMS  = {'a': 0.02, 'b': 0.25, 'c': -65.0, 'd': 2.00}


# TODO: Add mechanisms analogous to axon & dendrite propagation delay.


class IZNodeGene(BaseGene):
    __gene_attributes__ = [FloatAttribute('bias'),
                           FloatAttribute('a'),
                           FloatAttribute('b'),
                           FloatAttribute('c'),
                           FloatAttribute('d')]

    @classmethod
    def parse_config(cls, config, param_dict):
        return DefaultGeneConfig(cls.__gene_attributes__, param_dict)

    def distance(self, other, config):
        s = abs(self.a - other.a) + abs(self.b - other.b) \
            + abs(self.c - other.c) + abs(self.d - other.d)
        return s * config.compatibility_weight_coefficient


class IZGenome(DefaultGenome):
    @staticmethod
    def parse_config(param_dict):
        param_dict['node_gene_type'] = IZNodeGene
        param_dict['connection_gene_type'] = DefaultConnectionGene
        return DefaultGenomeConfig(param_dict)


class IZNeuron(object):
    def __init__(self, bias, a, b, c, d, inputs):
        """
        a, b, c, d are the parameters of the Izhikevich model.
        inputs: list of (input key, weight) pairs for incoming connections
        """
        self.a = a
        self.b = b
        self.c = c
        self.d = d
        self.bias = bias
        self.inputs = inputs

        # Membrane potential (millivolts).
        self.v = self.c

        # Membrane recovery variable.
        self.u = self.b * self.v

        self.fired = 0.0
        self.current = self.bias

    def advance(self, dt_msec):
        """
        Advances simulation time by the given time step in milliseconds.

        v' = 0.04 * v^2 + 5v + 140 - u + I
        u' = a * (b * v - u)

        if v >= 30 then
            v <- c, u <- u + d
        """
        # TODO: Make the time step adjustable, and choose an appropriate
        # numerical integration method to maintain stability.
        # TODO: The need to catch overflows indicates that the current method is
        # not stable for all possible network configurations and states.
        try:
            self.v += 0.5 * dt_msec * (0.04 * self.v ** 2 + 5 * self.v + 140 - self.u + self.current)
            self.v += 0.5 * dt_msec * (0.04 * self.v ** 2 + 5 * self.v + 140 - self.u + self.current)
            self.u += dt_msec * self.a * (self.b * self.v - self.u)
        except OverflowError:
            # Reset without producing a spike.
            self.v = self.c
            self.u = self.b * self.v

        self.fired = 0.0
        if self.v > 30.0:
            # Output spike and reset.
            self.fired = 1.0
            self.v = self.c
            self.u += self.d

    def reset(self):
        """Resets all state variables."""
        self.v = self.c
        self.u = self.b * self.v
        self.fired = 0.0
        self.current = self.bias


class IZNN(object):
    def __init__(self, neurons, inputs, outputs):
        self.neurons = neurons
        self.inputs = inputs
        self.outputs = outputs
        self.input_values = {}

    def set_inputs(self, inputs):
        """Assign input voltages."""
        assert len(inputs) == len(self.inputs)
        for i, v in zip(self.inputs, inputs):
            self.input_values[i] = v

    def reset(self):
        """Reset all neurons to their default state."""
        for i, n in self.neurons.items():
            n.reset()

    def get_time_step_msec(self):
        return 0.05

    def advance(self, dt_msec):
        for n in itervalues(self.neurons):
            n.current = n.bias
            for i, w in n.inputs:
                ineuron = self.neurons.get(i)
                if ineuron is not None:
                    ivalue = ineuron.fired
                else:
                    ivalue = self.input_values[i]

                n.current += ivalue * w

        for n in itervalues(self.neurons):
            n.advance(dt_msec)

        return [self.neurons[i].fired for i in self.outputs]

    @staticmethod
    def create(genome, config):
        """ Receives a genome and returns its phenotype (a neural network). """
        genome_config = config.genome_config
        required = required_for_output(genome_config.input_keys, genome_config.output_keys, genome.connections)

        # Gather inputs and expressed connections.
        node_inputs = {}
        for cg in itervalues(genome.connections):
            if not cg.enabled:
                continue

            i, o = cg.key
            if o not in required and i not in required:
                continue

            if o not in node_inputs:
                node_inputs[o] = [(i, cg.weight)]
            else:
                node_inputs[o].append((i, cg.weight))

        neurons = {}
        for node_key in required:
            ng = genome.nodes[node_key]
            inputs = node_inputs.get(node_key, [])
            neurons[node_key] = IZNeuron(ng.bias, ng.a, ng.b, ng.c, ng.d, inputs)

        genome_config = config.genome_config
        return IZNN(neurons, genome_config.input_keys, genome_config.output_keys)
