'''
Lots of people have this kind of self-heating model, but as far as I know they have not really
explored it adequately or done much analysis, probably because they actually use guis like
ltspice and of course you cannot accomplish anything doing that.

Done previously, but I can do it better:
Series resistance variation
Ambient temperature variation

+-20% variation of every parameter
Sweep rate variation
Device geometry variation (with speed)
small signal frequency response at different DC offsets
Pulse response with runaway and without
Conduction mechanism variation
energy barrier variation
Thermal resistance variation
fitting data to measure Rth, Cth
'''
from ltspice_control import *
from functools import partial, wraps
import numpy as np
#from ivtools.plot import *

netlist = netlist_fromfile('empirical.net')

# redefine read_raw to rename some of the dumb spice node names
# TODO: do this better. 
def read_raw_wrapper(read_raw):
    @wraps(read_raw)
    def new_read_raw(*args, **kwargs):
        datain = read_raw(*args, **kwargs)
        dataout = datain.copy()
        namemap = {'V(vd)': 'Vd',
                   'V(t)': 'T',
                   'V(vin)': 'V',
                   'I(Rd)': 'I',
                   'time': 't'}
        for oldk, newk in namemap.items():
            if oldk in datain:
                dataout[newk] = datain[oldk]
                del dataout[oldk]
        return dataout
    return new_read_raw
read_raw = read_raw_wrapper(read_raw)

# Parameters from my paper
#mech10 = partial(empirical_1, A=13275.47, Eb=.276759, c=0.000275)
#mech30 = partial(empirical_1, A=14287.41, Eb=.259994, c=0.000260)
#mech90 = partial(empirical_1, A=15663.10, Eb=.237437, c=0.000269)

@ivfunc
def max_ndr(data):
    # Doesn't work very well
    div = diffiv(data)
    return np.min(div['Vd']/div['I'])

# TODO
def explain_this(dataset):
    ''' Take in a dataset (which can have some varied parameters) and vary the other parameters in order to fit the IVs'''
    pass

### Vary every parameter by +-20%
netparams = get_params(netlist)
folder = 'param_variations'
if not os.path.isdir(folder):
    os.makedirs(folder)
# Do simulations
for k,v in netparams.items():
    data = []
    for val in np.linspace(v*.8, v*1.2, 10):
        newnetlist = netinsert(netlist, param(k, val))
        d = runspice(newnetlist)
        data.append(d)
    df = pd.DataFrame(data)
    df['V'] = df['V(vd)']
    df['I'] = df['I(Rd)']
    # Save some output files
    picklepath = os.path.join(folder, f'{k}_variation.df')
    df.to_pickle(picklepath)
    # Lol
    df[k] = np.float32(df[k].apply(lambda v: format(v, '.2e')))
    plotiv(df, x='V(vd)', y='I(Rd)', labels=k)
    plt.xlabel('Device Voltage [V]')
    plt.ylabel('Current [A]')
    plt.legend(title=f'{k}')
    pngpath = os.path.join(folder, f'{k}_variation.png')
    plt.savefig(pngpath)
