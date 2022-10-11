'''
Let's see how clunky it is to define and run ltspice simulations from python.
Will be possible to express much more complicated operations than in the spice language

As far as I know, we must communicate with ltspice via file io

Just need to translate python into spice language.
More often we will input existing netlists and modify them.
I'm taking a ~functional programming approach for fun, but could imagine an object oriented way that could be ok, too.

There is a library by Nuno Brum called PyLTSpice, which I tested and it seems to work.
https://github.com/nunobrum/PyLTSpice
Problem is he wrote his own data container classes which are clunky and I don't want to use them.
I want to use built-in data classes, like dict and list
which can be converted into well established and maintained containers like pandas series and dataframes for further analysis.

There's also this, which I haven't tested
https://github.com/DongHoonPark/ltspice_pytool
'''
#TODO: Spice can't tolerate spaces in equations, which makes them really hard to read.
# It took me an hour to realize this, anything following a space is just ignored
# We could easily allow spaces here and then always delete them before writing to disk
#TODO: Spice is case insensitive -- change everything to account for that
#TODO: Spice has lots of different syntax for the same thing.  e.g. .param name value  .PARAM name=value ..
#      write a better parser

import subprocess
import os
import re
import numpy as np
from collections.abc import Iterable
from datetime import datetime
import time
import fnmatch
from numbers import Number
from functools import reduce, partial
import warnings
import hashlib

# ltspice uses whatever encoding it feels like using, needs to be detected
# I think it takes cues from what kind of characters you use in the GUI
import chardet

# Make sure this points to your spice executable, and that it is the XVII version
spicepath = r"C:\Program Files\LTC\LTspiceXVII\XVIIx64.exe"

# Here is where all the simulation files (netlists and results) will be dumped
# It can get quite large if you don't delete the files afterward
simfolder = r"ltspice_sims"
simfolder = os.path.abspath(simfolder)

if not os.path.isdir(simfolder):
    os.makedirs(simfolder)

net_hashes = dict()

# Sample netlist -- list of strings
netlist = '''
* Example netlist
V1 in 0 PULSE(0 5 1m 1n 1n 10m)
R1 in N001 {R}
L1 N001 N002 {L}
C1 N002 0 {C}
.PARAM C=1e-6
.PARAM L=1e-3
.PARAM R=1
.tran 0 10m 0
.backanno
.end
'''.strip().split('\n')

def read_and_decode(filepath):
    ''' Use this to read a file if you don't know what the encoding is '''
    with open(filepath, 'rb') as f:
        data = f.read()
    encoding = chardet.detect(data)['encoding']
    return data.decode(encoding)

### File IO
def netlist_fromfile(filepath):
    ''' Read ltspice .net file.  Return a list of strings'''
    netlist = read_and_decode(filepath).split('\n')
    return [nl.strip() for nl in netlist if nl]

def read_log(filepath):
    ''' Read ltspice .log file and parse out some information.  Return a dict'''
    filepath = replace_ext(filepath, 'log')
    print(f'Reading {filepath}')
    lines = read_and_decode(filepath)
    logitems = re.findall('(.[^\s]*)[=,:] (.*)', lines)
    if not logitems:
        # quick fix, don't know why, but sometimes we have utf-16 encoding and sometimes not
        # chardet can't seem to detect this
        with open(filepath, 'r', encoding='utf-16-le') as f:
            lines = f.read()
        logitems = re.findall('(.[^\s]*)[=,:] (.*)', lines)
    def convert_vals(val):
        val = val.strip()
        if val.isdigit():
            val = np.int32(val)
        return val
    # might have more than one of each type (e.g. multiple WARNINGs)
    # store them as lists of strings if there are multiple and regret it later
    logdict = {}
    for k,v in logitems:
        key = k.strip()
        if key in logdict:
            if not isinstance(logdict[key], list):
                logdict[key] = [logdict[key]]
            logdict[key].append(convert_vals(v))
        else:
            logdict[key] = convert_vals(v)
    if 'Total elapsed time' in logdict:
        logdict['sim_time'] = np.float32(logdict['Total elapsed time'].split(' ')[0])
        del logdict['Total elapsed time']
    return logdict

def read_net(filepath):
    ''' Read ltspice .net file and parse out some information.  Return a dict'''
    netinfo = {}
    filepath = replace_ext(filepath, 'net')
    print(f'Reading {filepath}')
    netlist = netlist_fromfile(filepath)
    netparams = get_params(netlist)
    #netfuncs = re.findall('.FUNC (.*)=(.*)', netlist)
    #netfuncs = {k:v for k,v in netfuncs}
    netinfo['netlist'] = netlist
    netinfo.update(netparams)
    return netinfo

def read_raw(filepath):
    '''
    Read ltspice output .raw file.
    return dict of parameters and arrays contained in the file
    for ltspice XVII version
    Does not load parameter runs because I think those should just be done in python
    '''
    filepath = os.path.abspath(filepath)
    filepath = replace_ext(filepath, 'raw')

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
        # d is a dreaded numpy structured array
        d = np.fromfile(raw_file, dtype)
        ddict = {k:d[k] for k in colnames}
        # I have no idea why this is necessary
        if 'time' in ddict:
            ddict['time'] = np.abs(ddict['time'])
        for k,v in ddict.items():
            if v.size == 1:
                # numpy 0d arrays are stupid
                ddict[k] = v.item()
    # Put data and metadata together in one dict
    outdict = {**raw_params, **ddict}

    return outdict

def read_spice(filepath, namemap=None):
    ''' Read all the information contained in all the spice files with the same name (.raw, .net, .log)'''
    filepath = os.path.abspath(filepath)

    rawdata = read_raw(filepath)
    logdata = read_log(filepath)
    netdata = read_net(filepath)

    # Pick and choose the data you want to output
    dataout = {**rawdata, **netdata}
    dataout['sim_time'] = logdata.get('sim_time')
    dataout['solver'] = logdata.get('solver')
    dataout['method'] = logdata.get('method')
    dataout['WARNING'] = logdata.get('WARNING')

    # Map to other names if you want
    if namemap is not None:
        for oldk, newk in namemap.items():
            if oldk in dataout:
                dataout[newk] = dataout[oldk]
                del dataout[oldk]

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

def hash(netlist):
    return hashlib.md5(bytes('\n'.join(netlist), 'utf-8')).hexdigest()

def from_cache(netlist, namemap=None):
    ''' Check whether the same netlist has already been run, and if yes, return the results written to disk'''
    # Update cache
    existing_fns = fnmatch.filter(os.listdir(simfolder), '*.net')
    for fn in existing_fns:
        if fn not in net_hashes.values():
            existing_net = netlist_fromfile(os.path.join(simfolder, fn))
            #net_hashes[fn] = hash(existing_net)
            net_hashes[hash(existing_net)] = fn
    # Check if hash already in the cache
    h = hash(netlist)
    if h in net_hashes:
        print('Loading previous matching sim from disk')
        return read_spice(os.path.join(simfolder, net_hashes[h]), namemap=namemap)


# TODO somehow stop spice from stealing focus even though no window is visible
# TODO cache some inputs and outputs, so that you don't keep running the same simulations
# at least cache the file locations
#from functools import lru_cache
#@lru_cache(maxsize=32)
def runspice(netlist, namemap=None, timeout=None, check_cache=True):
    ''' Run a netlist with ltspice and return all the output data '''
    # TODO: Sometimes when spice has an error, python just hangs forever.  Need a timeout or something.
    # TODO: is there any benefit to spawning many ltspice processes at once, instead of sequentially?
    if type(netlist) is str:
        netlist = netlist.split('\n')
    if check_cache:
        old_result = from_cache(netlist)
        if old_result: return old_result
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
    # If error/timeout, maybe we want to keep running things, don't raise the error just return empty data
    try:
        subprocess.check_output([spicepath, '-b', '-Run', netlistfp], timeout=timeout)
    except subprocess.CalledProcessError as err:
        print(err)
        print(read_log(replace_ext(netlistfp, 'log')))
        return {}
    except subprocess.TimeoutExpired as err:
        print(err)
        return {}

    #subprocess.check_output([spicepath, '-b', '-ascii', '-Run', netlistfp])
    # Read result
    rawfp = os.path.splitext(netlistfp)[0] + '.raw'
    d = read_spice(rawfp, namemap=namemap)
    t1 = time.time()
    # Sim time including file io
    d['sim_time_total'] = t1 - t0
    return d

def recentfile(filter='', n=0, folder=simfolder):
    ''' Return the nth most recent filepath'''
    filter = f'*{filter}*'
    dirlist = os.listdir(folder)
    matches = fnmatch.filter(dirlist, filter)
    matchingfps = [os.path.join(folder, m) for m in matches]
    # might be able to just assume they are in sorted order because of the file names...
    recent = np.argsort([os.path.getmtime(f) for f in matchingfps])
    return os.path.join(folder, matches[recent[-1-n]])


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
def netinsert(netlist, newline):
    '''
    Replace a line in the netlist if it corresponds to an existing command,
    or else add it as a new line in a reasonable position
    Does not check if you are putting in a command that makes sense or will run!
    Return the netlist with the inserted line
    '''
    # Spice language is not very uniform so it's not completely trivial how to decide
    # When to replace a line or when to add a new line.

    netlist = netlist.copy()

    # Find the part of the string that identifies what the command does
    cmd, *rest = newline.split(' ', 1)
    if cmd.lower() in ('.param', '.func', '.ic'):
        # Compare also with the thing before the = sign
        cmd_id = newline[:newline.find('=') + 1]
    else:
        cmd_id = cmd

    # How similar is each line to the identifying string?
    # I will put the new line after the one most similar to it
    # There's probably a better approach.
    def similarity(netlist, line):
        '''
        Return the number of characters that are the same as 'line' for each line of netlist
        '''
        # This is not the most efficient thing ever but who cares
        def compare(str1, str2):
            if str1.lower().startswith(str2.lower()):
                return len(str2)
            else:
                return [c1.lower() == c2.lower() for c1,c2 in zip(str1, str2)].index(False)
        return [compare(l, line) for l in netlist]

    simi = similarity(netlist, cmd_id)
    maxsim = max(simi)
    if maxsim == len(cmd_id):
        # Replace existing line
        i = simi.index(maxsim)
        netlist[i] = newline
    else:
        # Find a good index to insert the new line
        # (After the most similar line)
        i = np.argmax(simi) + 1
        netlist.insert(i, newline)

    return netlist

def netchange(netlist, *newlines):
    '''
    Pass any (potentially nested) list of strings and merge them with netlist
    Return the resulting merged netlist
    '''
    strings = flatten(newlines)
    return reduce(netinsert, strings, netlist)

def netchanger(netlist):
    ''' Closure that remembers the input netlist, and allows you to modify it by passing partial netlists '''
    changer = partial(netchange, netlist)
    return changer

def paramchange(netlist, paramdict=None, **kwargs):
    '''
    If you only want to change .PARAMS, you can pass a dict of them to this function
    Or pass them as keyword arguments, or both
    '''
    newparams = []
    if paramdict is not None:
        newparams += [param(k, v) for k,v in paramdict.items()]
    if kwargs:
        newparams += [param(k, v) for k,v in kwargs.items()]
    newnet = netchange(netlist, newparams)
    return newnet

def set_title(netlist, title):
    '''
    First line is always the title?
    Needs its own function because netinsert won't know how to identify and replace the title line
    '''
    return [title] + netlist[1:]

def flatten(nested):
    ''' flatten a tree of strings '''
    for i in nested:
            if isinstance(i, Iterable) and not isinstance(i, str):
                for subc in flatten(i):
                    yield subc
            else:
                yield i


### Spice directives
def param(name, value):
    return f'.PARAM {name}={value}'

def function(funcdef):
    funcdef = funcdef.replace(' ', '')
    return f'.FUNC {funcdef}'

def element(name, cathode, anode, val):
    '''
    For now we do not distinguish the element types.
    Spice will use the first letter of the name to decide what kind of element it is
    TODO: Overwrite value without specifying cathode and anode
    TODO: Autoname if name not given.
    Don't know how this would work, as we would need to be aware of the netlist that it is getting applied to, but we already return a string before that happens.
    '''
    return f'{name} {cathode} {anode} {val}'

# TODO: make functions for common elements.
#def resistor():
#def capacitor():
#def inductor():

def transient(start=0, stop=1, maxstep=1e-4, stopsteady=False):
    cmd = f'.tran 0 {stop} {start} {maxstep}'
    if stopsteady:
        cmd += ' steady'
    return cmd

def initial_condition(name, value):
    return f'.ic {name}={value}'

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
    # Try changing all parameters by ±50%
    datalist = []
    for name, value in get_params(netlist).items():
        for v in np.linspace(0.5*value, 1.5*value, 5):
            data = runspice(netchange(netlist, param(name, v)))
            datalist.append(data)

    plt.figure()
    for data in datalist:
        plt.plot(data['time'], data['I(R1)'])

    #df = pd.DataFrame(datalist)


