# -*- coding: utf-8 -*-

## Copyright 2015-2017 Frankfurt Institute for Advanced Studies

## This program is free software; you can redistribute it and/or
## modify it under the terms of the GNU General Public License as
## published by the Free Software Foundation; either version 3 of the
## License, or (at your option) any later version.

## This program is distributed in the hope that it will be useful,
## but WITHOUT ANY WARRANTY; without even the implied warranty of
## MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
## GNU General Public License for more details.

## You should have received a copy of the GNU General Public License
## along with this program.  If not, see <http://www.gnu.org/licenses/>.

"""

"""

from __future__ import absolute_import

import numpy as np
import pandas as pd

import os
import glob
import pytz, datetime

from .decorators import cachable
from . import make_toDataDir
toDataDir = make_toDataDir(__file__)

@cachable(keepweakref=True)
def timeseries_entsoe(years=list(range(2011, 2015+1)), countries=None, directory=None):
    """
    Read consumption data from ENTSO-E country packages

    Parameters
    ----------
    years : list of int
        Years for which to read consumption data (defaults to
        2011-2015)
    countries : list or None
        Country names in the encoding of ENTSO-E as full names
        (refer to the data/entsoe_country_packages directory).
        If None, read data for all countries (default).

    Returns
    -------
    load : pd.DataFrame
        Load time-series with UTC timestamps x ISO-2 countries
    """

    # Only take into account years from 2006 to 2015
    years = [y for y in years if y >= 2006 and y <= 2015]

    if directory is None:
        directory = toDataDir('entsoe_country_packages')
    fns = sum((glob.glob(os.path.join(directory, '{}_{}.xls'.format(c, y)))
               for y in years
               for c in (('*',) if countries is None else countries)), [])
    def read_all_excel(fns):
        for fn in fns:
            try:
                yield pd.read_excel(fn, skiprows=6, header=0, sheetname='hourly_load_values', na_values=[u' '])
            except StopIteration:
                pass
    tz = pytz.timezone('Europe/Berlin')
    data = pd.concat(read_all_excel(fns))
    transdata = data.ix[:,['Country','Date/Time', '3B:00:00']] \
            .set_index(['Country', 'Date/Time']).stack().unstack(0)
    del data['3B:00:00']

    data = data \
        .set_index(['Country', 'Date/Time']) \
        .stack().unstack(0)

    transitions = [t for t in tz._utc_transition_times if t.year in years]
    since = datetime.datetime(years[0], 1, 1)
    for forward, backward in zip(*[iter(transitions)]*2):
        forward_ind = 24*(forward - since).days + 2
        backward_ind = 24*(backward - since).days + 2
        data.iloc[forward_ind:backward_ind+1] = data.iloc[forward_ind:backward_ind+1].shift(-1)
        try:
            data.iloc[backward_ind] = transdata.loc[backward.strftime("%Y-%m-%d"), "3B:00:00"]
        except KeyError:
            data.iloc[backward_ind] = data.iloc[backward_ind - 1]

    data = data \
        .set_index(pd.date_range('{}-01-01'.format(years[0]),
                                 '{}-01-01'.format(int(years[-1]) + 1),
                                 closed='left', freq='1h', tz=tz)) \
        .tz_convert(pytz.utc)

    if countries is None or set(('Kosovo', 'Albania')).issubset(countries):
        # manual alterations:
        # Kosovo gets the same load curve as Serbia
        # scaled by energy consumption ratio from IEA 2012
        data['KV'] = data['RS'] * (4.8 / 27.)
        # Albania gets the same load curve as Macedonia
        data['AL'] = data['MK'] * (4.1 / 7.4)

    return data


def timeseries_opsd(years=slice("2011", "2015"), countries=None):
    """
    Read load data from OPSD time-series package.

    Parameters
    ----------
    years : None or slice()
        Years for which to read load data (defaults to
        slice("2011","2016"))
    countries : list or None
        ISO-2 country codes as used by OPSD.

    Returns
    -------
    load : pd.DataFrame
        Load time-series with UTC timestamps x ISO-2 countries
    """

    load = (pd.read_csv(toDataDir('time_series_60min_singleindex_filtered.csv'), index_col=0, parse_dates=True)
            .loc[:, lambda df: df.columns.to_series().str.endswith('_load_old')]
            .rename(columns=lambda s: s[:-len('_load_old')])
            .dropna(how="all", axis=0))

    if countries is not None:
        load = load[countries]

    if years is not None:
        load = load.loc[years]

    if countries is None or set(('KV', 'AL')).issubset(countries):
        # manual alterations:
        # Kosovo gets the same load curve as Serbia
        # scaled by energy consumption ratio from IEA 2012
        load['KV'] = load['RS'] * (4.8 / 27.)
        # Albania gets the same load curve as Macedonia
        load['AL'] = load['MK'] * (4.1 / 7.4)

    if countries is None or 'GR' in countries:
        # To fill the half week gap in Greece from start to stop,
        # we copy the week before into it
        start = pd.Timestamp('2015-08-11 21:00')
        stop = pd.Timestamp('2015-08-15 20:00')
        w = pd.Timedelta(weeks=1)

        if start in load.index and stop in load.index:
            load.loc[start:stop, 'GR'] = load.loc[start-w:stop-w, 'GR'].values

    if countries is None or 'EE' in countries:
        # There are three missing hours in 2014 and four in 2015
        # we interpolate linearly (copying from the previous week
        # might be better)
        load['EE'] = load['EE'].interpolate()

    return load
