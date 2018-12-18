# Just some ideas that I don't want to execute ever

# Why do we want python control?
# 1. Need to get the resulting data into a programming language with reasonable analysis and plotting ability
# 2. In spice, you change things by clicking the mouse a million times, clicking run, and using the really shitty plotting tools
# 3. Spice does not have a command to execute itself, or analyze itself, so can't express some higher level operations
# 4. The spice language itself is not great, we really want to redesign the language, and have access to all the nice libraries that python has

# Would it be difficult to translate the entire spice language into python?
# What's the most productive syntax?

# is there any need for .PARAM statements if we can hold them in python variables?
# Would need to log the state of the namespace and include with the simulation results or something like that
# the .net files would also look really bad if you read them in plain text.  Just a bunch of numbers.

# possible python syntax?
a = 3
b = 4
c = 2
node1 = node()
node2 = node()
gnd = node(gnd=True)
C = capacitor(a * 1e-3, node1, node2)
R = resistor(b * 1e4, gnd, node2)
wire(node1, gnd)
# This function gets defined in spice
@spicefunc
def I(V):
    # How to refer to other functions defined in spice? quoting? need some really fancy parsing here..
    return exp(V**2/kT) * 'otherfunc'
# This function is just defined here in python
def condition(data):
    return data['V(R)'][0] > 3
# makes runspice return these values as well?
meta(a=a, b=b, c=c)
V = voltage(sine(freq=10, amp=2), gnd, node2)
transient(1, maxstep=1e-3)
d = runspice()
# Conditionally add something to the circuit and run again
if condition(d):
    L = inductor(c * 1e-5, node1, node2)
    d2 = runspice()

# Making a programming language in python is hard.  Maybe we need lisp.
# I think all those function calls would have to add/replace lines in the netlist as a side effect,
# and return some fancy objects that have useful __str__ and/or __repr__ or other attributes
# Hardest thing above is to write spicefunc
# But we could just use strings, and at least get rid of the annoyance of not being able to use spaces
I = spicefunc('exp(V^2/kT) * otherfunc')

# Where is the "getting shit done without hating my life" middle ground between:
# Using spice how you are supposed to use spice
# inventing an entirely new spice language that somehow translates itself to existing spice language through some complicated interoperation between spice process and python interpreter
# ?

# Python functions that evaluate to spice code
# Downsides?
# 1. params are not aware of other params
# 2.

def param(name, value):
    return f'.PARAM {name}={value}'

def element(name, cathode, anode, val):
    return f'{name} {cathode} {anode} {val}'

# Could give nodes python names
vin = 'vin'
modifications = [
                param('a', 3),
                param('b', 10),
                param('c', 'a*b'), # Quoted code is evaluated by spice.
                element('C2', vin, 0, 1e-9),
                transient(0, 1, 1e-4)
                ]
newnetlist = reduce(netinsert, modifications, netlist)

def simchange(netlist0):
    def newnetlist(*modifications):
        return reduce(netinsert, *modifications, netlist0)
    return newnetlist

simname = simchange(netlist)
newnetlist = simname(modifications)
d = runspice(newnetlist)

# Or..

def ndrparams():
    '''
    One way to define parameters.
    Nice syntax, doesn't pollute global namespace, computes values in python, not in spice
    So if there are parameters written in terms of other parameters, we will see the values
    in the netlist, not unevaluated strings.
    TODO: Would be really cool to put simple python functions in here and use the ast to convert into a string
        that spice can understand.  Then we can split functions into multiple lines, do more complicated things.
        How would we handle references to node current/voltages?  Pass undefined names into spice as strings?
    '''
    def Resistance():
        tox / wox**2 / A * exp(echarge * Ea / boltz / T()) * exp(-c * sqrt(E()))
    wox = 250e-9
    tox = 30e-9
    A = 14287.41
    c = 0.00026
    Rth50090 = 80000.0
    Rth = Rth50090 * 500e-9 / wox
    Ea = 0.26
    Rser = 5000.0
    Tamb = 300.0
    Cth50090 = 5e-12
    Cth = Cth50090 / 500e-9**2 / 90e-9 * wox**2 *tox
    sweepdur = 1.0
    sweepmax = 10.0
    return locals()
params = ndrparams()
net = netlist = paramchange(filenet, params)

# What about a decorator that automatically converts the locals to a netlist?
# You could still use spice code, just in quotes

# Could we use the above approach to also define functions/circuit elements/other directives?

# OO approach might look like this
class NetList(object):
    '''
    NOT DONE
    I'm tempted to go down the object oriented rabbit hole
    Could make a class that can parse and construct ltspice netlists
    Idea is to create a convenient python syntax which can modify an input netlist
    Could give every type of spice command an object, which just evaluate to strings

    maybe netlist[3] can retrieve and assign new lines
    maybe netlist.param2 = 45.3 can set .PARAMS, overwriting as necessary
    maybe netlist.wire(node1, node2) can add a wire
    maybe netlist.nodes() can return a list of node names (or node objects ....)
    maybe netlist.resistor(node1, node2, value, name=None) can add a resistor...
    maybe netlist.voltage(type, param2, param2,..) can add/change a voltage source
    maybe netlist + string can merge that line of code into the netlist

    since the content of the netlist string will depend on the state of the instance,
    we will need to construct it only when it is asked for

    Should also keep the lines organized in some way, connections at top, funcs, params, ...
    '''
    def __init__(self, netlist0='* New netlist'):
        # Can initalize with an existing netlist
        self._netstring = netlist0
        self._netlist = netlist0.split('\n')
        netparams = re.findall('.PARAM (.*)=(.*)', netlist0)
        # Are params always floats?
        netparams = {k:np.float32(v) for k,v in netparams}
        for k,v in netparams.items():
            setattr(self, k, v)

    def __repr__(self):
        # Just print the string
        return self.netlist

    def clear_params(self):
        for k in self.params().keys():
            del self.__dict__[k]

    @property
    def params(self):
        # Determine which class attributes are .PARAMS
        # Let's say all numbers are .PARAMS
        return {k:v for k,v in self.__dict__.items() if isinstance(v, Number)}

    @params.setter
    def params(self, values):
        # Can update params with a dict
        # Don't do params['paramname'] = value, this won't do anything
        #self.clear_params()
        self.__dict__.update(values)

    @property
    def netlist(self):
        #print('Constructing netlist...')
        for k,v in self.__dict__.items():
            if isinstance(v, Number):
                # TODO: this can replace a param, but cannot add or delete a param
                newnetlist = replaceparam(self._netstring, k, v)
                self._netstring = newnetlist
        return self._netstring

    @netlist.setter
    def netlist(self, value):
        self._netstring = value


sim = NetList(netlist0)
sim.a = 3
sim.b = 10
sim.c = sim.a * sim.b # Code is evaluated by python
sim += Capacitor(1, 'in', 0, 1e-9)
d = sim.run()

# Is this better? Interface seems at first to be nicer. But the complex code is in the class definitions
# Basically it looks nice on the surface, but it's a mess on the inside?
