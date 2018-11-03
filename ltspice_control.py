'''
Let's see how clunky it is to run spice sim from python.

As far as I know, we must communicate via file io

Just need to translate python into whatever shitty language spice is using
Or I could start by just making a few functions that modify existing spice code?
Probably better to work on lists of strings (spice commands) rather than one \n joined string
Or class that has the netlist, and stores .PARAMS as class params?

Would like to be able to programmatically generate the connectivities as well

Is it ever worth using spices ".STEP" ?  Or can I handle all looping in python?
Maybe the file io takes a really long time?  I heard you can only .step 3 parameters.

There is a library by Nuno Brum called PyLTSpice, which I tested and it seems to work
Problem is he wrote his own data container classes are clunky and I don't want to use them
I want to use built-in data classes, or well established and maintained classes like pandas series and dataframes
'''

import subprocess
import os
import re
import numpy as np
import pandas as pd
from datetime import datetime
import time
import fnmatch
from numbers import Number
from functools import reduce, partial

spicepath = r"C:\Program Files\LTC\LTspiceXVII\XVIIx64.exe"
simfolder = r"ltspice_sims"

if not os.path.isdir(simfolder):
    os.makedirs(simfolder)

netlist = '''
* Thermal NDR simulation
Rd vd 0 R=Resistance()
Rs vd vin R=Rser
C1 T 0 {Cth}
V1 vin 0 PWL(0 0 5 3 10 0)
B1 T 0 I=dTdt()
.FUNC dTdt()=-(Resistance()*i(Rd)**2-(v(T)-Tamb)/Rth)
.FUNC Resistance()=R0*exp(q*(Ea+deltav())/(boltz*v(T)))
.FUNC deltav()=-sqrt(q*E()/(pi*e0*er))
.FUNC dv()=v(vd)
.FUNC E()=dv()/dox
.PARAM R0=34
.PARAM Rth=1.75e5
.PARAM Ea=0.215
.PARAM Rser=330
.PARAM q=1.6e-19
.PARAM e0=8.85e-12
.PARAM er=45
.PARAM dox=18e-9
.PARAM Tamb=298
.PARAM Cth=5e-10
.ic v(T)=Tamb
.tran 0 10 0 1e-4
.backanno
.end
'''.strip().split('\n')

### File IO
def netlist_fromfile(filepath):
    with open(filepath, 'r') as f:
        netlist = f.readlines()
    return [nl.strip() for nl in netlist]

def read_log(filepath):
    ''' Read ltspice .log file and parse out some information. '''
    print(f'Reading {filepath}')
    with open(filepath, 'r', encoding='utf_16_le') as f:
        lines = f.read()
    logitems = re.findall('(.*)[=,:] (.*)', lines)
    def convert_vals(val):
        val = val.strip()
        if val.isdigit():
            val = np.int32(val)
        return val
    logdict = {k.strip():convert_vals(v) for k,v in logitems}
    if 'Total elapsed time' in logdict:
        logdict['sim_time'] = np.float32(logdict['Total elapsed time'].split(' ')[0])
        del logdict['Total elapsed time']
    return logdict

def read_net(filepath):
    ''' Read ltspice .net file and parse out some information. '''
    netinfo = {}
    print(f'Reading {filepath}')
    with open(filepath, 'r') as f:
        netlist = f.read()
    netlist = netlist.split('\n')
    netparams = get_params(netlist)
    #netfuncs = re.findall('.FUNC (.*)=(.*)', netlist)
    #netfuncs = {k:v for k,v in netfuncs}
    netinfo['netlist'] = netlist
    netinfo.update(netparams)
    return netinfo

def read_raw(filepath):
    '''
    Read ltspice output .raw file.  No bullshit.
    for ltspice XVII version
    return dict of parameters and arrays contained in the file
    Does not load parameter runs because I think those should just be done in python
    '''
    filepath = os.path.abspath(filepath)

    # Read information from the .raw file
    print(f'Reading {filepath}')
    with open(filepath, 'rb') as raw_file:
        colnames = []
        units = []
        raw_params = {'filepath': filepath}

        def readline():
            line = raw_file.readline()
            # Read the newline...
            raw_file.read(1)
            return line.decode(encoding='utf_16_le', errors='ignore')

        # Read the header
        line = readline()
        while not line.startswith('Variables:'):
            tag, value_str = line.split(':', 1)
            value_str = value_str.strip()
            if value_str.isdigit():
                value_str = int(value_str)
            raw_params[tag] = value_str
            line = readline()

        # Read the column names
        line = readline()
        while not line.startswith('Binary'):
            _, name, unit = line.strip().split('\t')
            colnames.append(name)
            units.append(unit)
            line = readline()

        # Read the numerical data
        # Time values are 8 bytes, rest are 4 bytes.
        # (raw_file_size - 930) / numpoints / ((numvars-1)*4 + 8) = 1
        numpoints = raw_params['No. Points']
        numvars = raw_params['No. Variables']
        dtype = np.dtype({'names':colnames,
                          'formats':[np.float64] + [np.float32]*(numvars - 1)})
        d = np.fromfile(raw_file, dtype)
        df = pd.DataFrame(d)
        # I have no idea why this is necessary
        df['time'] = np.abs(df['time'])
        dfdict = {k:np.array(v) for k,v in dict(df).items()}

    # Put data and metadata together in one dict
    outdict = {**raw_params, **dfdict}

    return outdict

def read_spice(filepath):
    ''' Read all the information contained in all the spice files with the same name (.raw, .net, .log)'''
    filepath = os.path.abspath(filepath)

    rawfile = replace_ext(filepath, 'raw')
    logfile = replace_ext(filepath, 'log')
    netfile = replace_ext(filepath, 'net')

    rawdata = read_raw(rawfile)
    logdata = read_log(logfile)
    netdata = read_net(netfile)

    # Pick and choose the data you want to output

    dataout = {**rawdata, **netdata}
    dataout['sim_time'] = logdata['sim_time']
    dataout['solver'] = logdata['solver']
    dataout['method'] = logdata['method']

    return dataout

def replace_ext(path, newext):
    return os.path.splitext(path)[0] + '.' + newext.strip('.')

def timestamp():
    ''' Timestamp string with ms accuracy '''
    return datetime.now().strftime('%Y-%m-%d_%H%M%S_%f')[:-3]

def valid_filename(s):
    s = str(s).strip().replace(' ', '_')
    return re.sub(r'(?u)[^-\w.]', '', s)
def write_wav(times, voltages, filename):
    # Some dumb code I found online from some guy who doesn't know what numpy is
    import struct

    def lin_interp(x0, x1, y0, y1, x):
        x0 = float(x0)
        x1 = float(x1)
        y0 = float(y0)
        y1 = float(y1)
        x = float(x)
        return y0 + (x - x0) * (y1 - y0) / (x1 - x0)

    with wave.open(filename, 'w') as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(44100)
        w.setnframes(0)
        w.setcomptype('NONE')
        w.writeframes(np.sin(np.linspace(0, 8000*2*pi, 100000)))
        m = max(max(voltages), -min(voltages))
        vrange = m

        values = bytes([])
        t = 0.0
        step = 1.0 / SAMPLING_RATE

        for i in range(len(voltages)-1):
            while times[i] <= t * step < times[i+1]:
                sample = lin_interp(times[i], times[i+1],
                    voltages[i], voltages[i+1], t*step) / vrange
                sample = 1 if sample >1 else sample
                sample = -1 if sample <-1 else sample
                d = struct.pack('<h',int(32767 * sample))
                values += d
                t += 1

        w.writeframes(values)

def runspice(netlist):
    ''' Run a netlist with ltspice and return all the output data '''
    if type(netlist) is str:
        netlist = netlist.split('\n')
    t0 = time.time()
    # Write netlist to disk
    title = valid_filename(get_title(netlist))
    netlistfp = os.path.join(simfolder, timestamp() + f'_{title}.net')
    netlistfp = os.path.abspath(netlistfp)
    print(f'Writing {netlistfp}')
    with open(netlistfp, 'w') as f:
        f.write('\n'.join(netlist))
    print(f'Executing {netlistfp}')
    # Tell spice to execute it
    try:
        subprocess.check_output([spicepath, '-b', '-Run', netlistfp])
    except subprocess.CalledProcessError:
        print(read_log(replace_ext(netlistfp, 'log')))
        raise

    #subprocess.check_output([spicepath, '-b', '-ascii', '-Run', netlistfp])
    # Read result
    rawfp = os.path.splitext(netlistfp)[0] + '.raw'
    d = read_spice(rawfp)
    t1 = time.time()
    # Sim time including file io
    d['sim_time_total'] = t1 - t0
    return d

def recent(n=0, filter=''):
    ''' Return the nth most recent filepath'''
    filter = f'*{filter}*'
    dirlist = os.listdir(simfolder)
    matches = fnmatch.filter(dirlist, filter)
    recent = np.argsort(os.path.getmtime(f) for f in matches)
    return matches[recent[-1-n]]


### Netlist parsing
def get_params(netlist):
    params = re.findall('.PARAM (.*)=(.*)', '\n'.join(netlist))
    params = {k:v for k,v in params}
    # Try to convert params to number
    for k,v in params.items():
        try:
            params[k] = np.float32(v)
        except ValueError:
            pass
    return params
def get_title(netlist):
    ''' My understanding is that the first line must always be the title '''
    if netlist[0].startswith('*'):
        title = netlist[0][1:].strip()
    else:
        title = netlist[0]
    return title


### Functions for operating on netlist
def similarity(netlist, line):
    '''
    Return the number of characters that are the same as 'line' for each line of netlist
    '''
    # This is not the most efficient thing ever but who cares
    def compare(str1, str2):
        if str1.startswith(str2):
            return len(str2)
        else:
            return [c1 == c2 for c1,c2 in zip(str1, str2)].index(False)
    return [compare(l, line) for l in netlist]

def netinsert(netlist, newline):
    '''
    Replace a line in the netlist if it corresponds to an existing command,
    or else add it as a new line in a reasonable position
    Does not check if you are putting in a command that makes sense or will run!
    '''
    # Spice language is not very uniform so it's not completely trivial how to decide
    # When to replace a line or when to add a new line.

    netlist = netlist.copy()

    # Find the part of the string that identifies what the command does
    cmd, *rest = newline.split(' ', 1)
    if cmd in ('.PARAM', '.FUNC', '.ic'):
        cmd_id = newline[:newline.find('=')]
    else:
        cmd_id = cmd

    # How similar is each line to the identifying string?
    # I will put the new line after the one most similar to it
    # There's probably a better approach.
    simi = similarity(netlist, cmd_id)
    maxsim = max(simi)
    if maxsim == len(cmd_id):
        # Replace existing line
        i = simi.index(maxsim)
        netlist[i] = newline
    else:
        # Find a good index to insert the new line
        # (After the most similar line)
        i = argmax(simi) + 1
        netlist.insert(i, newline)

    return netlist

def netchanger(netlist):
    def newnetlist(*modifications):
        return reduce(netinsert, *modifications, netlist)
    return newnetlist

def set_title(netlist, title):
    ''' First line is always the title? '''
    return [title] + netlist[1:]


### Spice directives
def param(name, value):
    return f'.PARAM {name}={value}'

def function(funcdef):
    return f'.FUNC {funcdef}'
def element(name, cathode, anode, val):
    '''
    For now we do not distinguish the element types.
    Spice will use the first letter of the name to decide what kind of element it is
    '''
    return f'{name} {cathode} {anode} {val}'

def transient(start=0, stop=1, maxstep=1e-4):
    return f'.tran 0 {stop} {start} {maxstep}'


### Spice waveforms
# TODO add some useful functions that translate into these (e.g. triangle..)
def sine(freq, amp, offset=0, delay=0, phase=0, damping=0, ncycles=None):
    ''' Phase in degrees '''
    if ncycles is None:
        ncycles = ''
    return f'SINE({offset} {amp} {freq} {delay} {damping} {phase} {ncycles})'
def pulse(Voff, Von, trise, ton, tfall, period=None, delay=0, ncycles=None):
    if period is None:
        period = trise + ton + tfall + delay
    if ncycles is None:
        ncycles = ''
    return f'PULSE({Voff} {Von} {delay} {trise} {tfall} {ton} {period} {ncycles})'

def PWL(t, v):
    ''' Piecewise Linear waveform. Should probably use wav file instead if this gets long.'''
    interleaved = (val for pair in zip(t, v) for val in pair)
    interleaved_str = ' '.join(format(v) for v in interleaved)
    return f'PWL({interleaved_str})'



if 0:
    data = []
    for T0 in range(300, 400, 10):
        # This is how you can change parameters
        netlist2 = netinsert(netlist, parameter('Tamb', T0))
        d = runspice(netlist2)
        data.append(d)
    df = pd.DataFrame(data)

# Just some ideas that I don't want to execute ever
if 0:
    # What if you did something like this?

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
