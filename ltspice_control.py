'''
Let's see how clunky it is to run spice sim from python.

As far as I know, we must communicate via file io

Just need to translate python into whatever shitty language spice is using
Or I could start by just making a few functions that modify existing spice code?
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

spicepath = r"C:\Program Files\LTC\LTspiceXVII\XVIIx64.exe"
simfolder = r"ltspice_sims"

netlist = '''
* Title
R1 vm 0 R=Resistance()
Rs vm vin R=Rser
C1 T 0 5e-10
V1 N001 0 PWL(0 0 5 3 10 0)
R2 N001 vin 0.1
B1 T 0 I=dTdt()
.FUNC dTdt()=-(Resistance()*i(R1)**2-(v(T)-Tamb)*gammath)
.FUNC Resistance()=R0*exp(q*(Ea+deltav())/(k*v(T)))
.FUNC deltav()=-sqrt(q*E()/(pi*e0*er))
.FUNC dv()=v(vm)
.FUNC E()=dv()/dox
.PARAM R0=34
.PARAM gammath=5.7e-6
.PARAM Ea=0.215
.PARAM k=1.38e-23
.PARAM Rser=330
.PARAM q=1.6e-19
.PARAM e0=8.85e-12
.PARAM er=45
.PARAM dox=18e-9
.PARAM Tamb=298
.ic  v(T)=Tamb
.tran 0 10 0 1e-4
.backanno
.end
'''

def replaceparam(netlist, paramname, newvalue):
    ''' Replace a single param in the netlist if it exists. '''
    loc = netlist.find(f'.PARAM {paramname}')
    if loc > 0:
        paramstart = loc + netlist[loc:].find('=') + 1
        paramend = loc + netlist[loc:].find('\n')
        return netlist[:paramstart] + str(newvalue) + netlist[paramend:]
    else:
        (f'Did not find .PARAM {paramname} in the netlist!')
        return netlist

def changeparams(netlist, **kwargs):
    ''' Replaces parameters in the input netlist and returns a new netlist '''
    if len(kwargs) > 0:
        k,v = kwargs.popitem()
        return changeparams(replaceparam(netlist, k, v), **kwargs)
    else:
        return netlist

def runspice(netlist):
    ''' Run a netlist with ltspice and return all the output data '''
    t0 = time.time()
    # Write netlist to disk
    netlistfp = os.path.join(simfolder, timestamp() + '_test.net')
    with open(netlistfp, 'w') as f:
        f.write(netlist)
    # Tell spice to execute it
    subprocess.check_output([spicepath, '-b', '-Run', netlistfp])
    #subprocess.check_output([spicepath, '-b', '-ascii', '-Run', netlistfp])
    # Read result
    rawfp = os.path.splitext(netlistfp)[0] + '.raw'
    d = read_spice(rawfp)
    t1 = time.time()
    # Sim time including file io
    d['sim_time_total'] = t1 - t0
    return d


def replace_ext(path, newext):
    return os.path.splitext(path)[0] + '.' + newext.strip('.')

def timestamp():
    ''' Timestamp string with ms accuracy '''
    return datetime.now().strftime('%Y-%m-%d_%H%M%S_%f')[:-3]


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
    netparams = re.findall('.PARAM (.*)=(.*)', netlist)
    netparams = {k:np.float32(v) for k,v in netparams}
    netfuncs = re.findall('.FUNC (.*)=(.*)', netlist)
    netfuncs = {k:v for k,v in netfuncs}
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


if 0:
    data = []
    for T0 in range(300, 400, 10):
        # This is how you can change parameters
        netlist2 = changeparams(netlist, Tamb=T0)
        d = runspice(netlist2)
        data.append(d)
    df = pd.DataFrame(data)

