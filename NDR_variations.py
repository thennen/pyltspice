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
from functools import partial

netlist0 = '''
Thermal NDR simulation
Rd vd 0 R=Resistance()
Rs vd vin R=Rser
C1 T 0 {Cth}
V1 vin 0 PWL(0 0 5 3 10 0)
B1 T 0 I=dTdt()
.FUNC dTdt()=-(Resistance()*i(Rd)**2-(v(T)-Tamb)/Rth)
.FUNC Resistance()=R0*exp(echarge*(Ea+deltav())/(boltz*v(T)))
.FUNC deltav()=-sqrt(echarge*E()/(pi*e0*er))
.FUNC dv()=v(vd)
.FUNC E()=dv()/dox
.PARAM R0=34
.PARAM Rth=1.75e5
.PARAM Ea=0.215
.PARAM Rser=200
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

# Attempt to capture the cell shape dependence
netlist1 = '''
* Thermal NDR simulation
Rd vd 0 R=Resistance()
Rs vd vin R=Rser
C1 T 0 {Cth*width**2*thickness}
V1 vin 0 PWL(0 0 5 3 10 0)
B1 T 0 I=dTdt()
.FUNC dTdt()=-(Resistance()*i(Rd)**2-(v(T)-Tamb)/Rth*width)
.FUNC Resistance()=R0*thickness/width**2 * exp(echarge*(Ea+deltav())/(boltz*v(T)))
.FUNC deltav()=-sqrt(echarge*E()/(pi*e0*er))
.FUNC dv()=v(vd)
.FUNC E()=dv()/thickness
.PARAM thickness=18e-9
.PARAM width=500e-9
.PARAM R0=4.72e-4
.PARAM Rth=0.0875
.PARAM Ea=0.215
.PARAM Rser=200
.PARAM e0=8.85e-12
.PARAM er=45
.PARAM Tamb=298
.PARAM Cth=11.11e11
.ic v(T)=Tamb
.tran 0 10 0 1e-4
.backanno
.end
'''.strip().split('\n')

# Vary every parameter by +-20%
netparams = get_params(netlist0)
folder = 'param_variations'
if not os.path.isdir(folder):
    os.makedirs(folder)
for k,v in netparams.items():
    data = []
    for val in linspace(v*.8, v*1.2, 10):
        netlist = replaceparam(netlist0, k, val)
        d = runspice(netlist)
        data.append(d)
    df = pd.DataFrame(data)
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
