""" Outsourced C function bindings for volume conversion in the pulse interface datatypes.

Loading this module requires libpulse to be installed.
"""
import ctypes as c
import ctypes.util
from pulsectl._pulsectl import PA_CVOLUME, PA_CHANNEL_MAP


libpulse = c.CDLL(ctypes.util.find_library('libpulse') or 'libpulse.so.0')

pa_volume_t = c.c_uint32
pa_cvolume_max = libpulse.pa_cvolume_max
pa_cvolume_max.argtypes = [c.POINTER(PA_CVOLUME)]
pa_cvolume_max.restype = pa_volume_t
pa_cvolume_get_balance = libpulse.pa_cvolume_get_balance
pa_cvolume_get_balance.argtypes = [c.POINTER(PA_CVOLUME), c.POINTER(PA_CHANNEL_MAP)]
pa_cvolume_get_balance.restype = c.c_float
pa_cvolume_get_fade = libpulse.pa_cvolume_get_fade
pa_cvolume_get_fade.argtypes = [c.POINTER(PA_CVOLUME), c.POINTER(PA_CHANNEL_MAP)]
pa_cvolume_get_fade.restype = c.c_float
pa_cvolume_get_lfe_balance = libpulse.pa_cvolume_get_lfe_balance
pa_cvolume_get_lfe_balance.argtypes = [c.POINTER(PA_CVOLUME), c.POINTER(PA_CHANNEL_MAP)]
pa_cvolume_get_lfe_balance.restype = c.c_float
pa_cvolume_set_balance = libpulse.pa_cvolume_set_balance
pa_cvolume_set_balance.argtypes = [c.POINTER(PA_CVOLUME), c.POINTER(PA_CHANNEL_MAP), c.c_float]
pa_cvolume_set_balance.restype = None
pa_cvolume_set_fade = libpulse.pa_cvolume_set_fade
pa_cvolume_set_fade.argtypes = [c.POINTER(PA_CVOLUME), c.POINTER(PA_CHANNEL_MAP), c.c_float]
pa_cvolume_set_fade.restype = None
pa_cvolume_set_lfe_balance = libpulse.pa_cvolume_set_lfe_balance
pa_cvolume_set_lfe_balance.argtypes = [c.POINTER(PA_CVOLUME), c.POINTER(PA_CHANNEL_MAP), c.c_float]
pa_cvolume_set_lfe_balance.restype = None
pa_cvolume_scale = libpulse.pa_cvolume_scale
pa_cvolume_scale.argtypes = [c.POINTER(PA_CVOLUME), pa_volume_t]
pa_cvolume_scale.restype = None
