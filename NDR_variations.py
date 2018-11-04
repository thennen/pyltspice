'''
Lots of people have this kind of self-heating model, but as far as I know they have not really
explored it adequately or done much analysis, probably because they actually use guis like
ltspice and of course you cannot accomplish anything doing that.

Done previously, but I can do it better:
Series resistance variation
Ambient temperature variation

+-20% variation of every parameter for fun?
Sweep rate variation
Device geometry variation (with speed)
small signal frequency response at different DC offsets
Pulse response with runaway and without
Conduction mechanism variation
energy barrier variation
Thermal resistance variation, different kinds of scaling?
fitting data to measure Rth, Cth
forming simulation by using parallel element and internal series resistance
'''
from ltspice_control import *
from functools import partial, wraps
import numpy as np
#from ivtools.plot import *

net = netlist = netlist_fromfile('empirical.net')

# don't know if this is a dumb name or not
deltanet = netchanger(net)

params = {'A': 14287.41,
          'Cth': 'Cth50090/500e-9/500e-9/90e-9*wox*wox*tox',
          'Cth50090': 5e-12,
          'Ea': 0.26,
          'Rser': 5000.0,
          'Rth': 'Rth50090*500e-9/wox',
          'Rth50090': 80000.0,
          'Tamb': 300.0,
          'c': 0.00026,
          'sweepdur': 1.0,
          'sweepmax': 10.0,
          'tox': 3e-08,
          'wox': 5e-07}

# redefine read_raw to rename some of the dumb spice node names
# TODO: do this better. ltspice_control.read_spice does not get the wrapped function

namemap = {'V(vd)': 'Vd',
           'V(t)': 'T',
           'V(vin)': 'V',
           'I(Rd)': 'I',
           'time': 't'}
read_spice = partial(read_spice, namemap=namemap)


### High level functions which return partial netlists to merge into base netlist
def sqpulse(vmin, vmax, duration, risetime):
    ''' Applies a square pulse and measures the transient response '''
    delay = duration * .1
    totaltime = duration*2
    return [element('V1', 'vin', 0, pulse(vmin, vmax, risetime, duration, risetime, totaltime, delay)),
                   transient(0, totaltime, totaltime/10000)]

def parallel_cap(value):
    ''' Puts a parasitic capacitor in parallel with device '''
    return element('C2', 'vd', 0, value)

###

@ivfunc
def max_ndr(data):
    # Doesn't work very well
    div = diffiv(data)
    mask = np.abs(div['Vd']) > 4e-5
    return np.min(div['Vd'][mask]/div['I'][mask])

# TODO
def explain_this(dataset):
    ''' Take in a dataset (which can have some varied parameters) and vary the other parameters in order to fit the IVs'''
    pass

### Make sure we can reproduce results from IEDM paper, way slower than original (because time dependence)
data = []
plt.figure()
# Parameters determined from fits to data
tparams = {10:{'A':13275.47, 'Ea':.276759, 'c':0.000275},
           30:{'A':14287.41, 'Ea':.259994, 'c':0.000260},
           90:{'A':15663.10, 'Ea':.237437, 'c':0.000269}}
for t in (90, 30, 10):
    for w in (500, 350, 250, 150, 120):
        newparams = [param(k, v) for k,v in tparams[t].items()]
        newparams += [param('sweepmax', 8),
                      param('tox', t*1e-9),
                      param('wox', w*1e-9),
                      param('Rser', 10000)]
        newnet = netchanger(net)(newparams)
        d = runspice(newnet)
        data.append(d)
        plotiv(d, x='Vd', y='I', ax=gca())
        plt.pause(.1)

### Sweep rate variation
deltanet = netchanger(net)
data = []
for dur in logspace(0, -8, 8):
    newnet = deltanet([param('wox', 300e-9),
                       param('Rser', Rs)])
    d = runspice(newnet)
    data.append(d)
plotiv(d, x='Vd', y='I', ax=gca())


# Pulse dynamics
# find steady state NDR point, pulse relative to that?

def pulse(Voff, Von, trise, ton, tfall, period=None, delay=0, ncycles=None):



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
