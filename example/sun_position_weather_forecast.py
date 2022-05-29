# Copyright 2022 Michael Thies <mail@mhthies.de>
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may not use this file except in compliance with
# the License. You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software distributed under the License is distributed on an
# "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the License for the
# specific language governing permissions and limitations under the License.
"""
This sample script shows how external Python libraries and web services can be used with SHC applications, specifically
how to load the weather forecast from OpenWeatherMap and use AstroPy to calculate the current position of the sun.
"""
import asyncio
import datetime
import logging
from typing import Tuple

import aiohttp

import shc
import shc.timer


# Configuration of your place on earth and your OpenWeatherMap API credentials
# You may want to load this from a configuration file in production use
# To get an OpenWeatherMap API key, sign up for a user account at https://home.openweathermap.org/users/sign_up and
# navigate to "My API keys"
POSITION_LONGITUDE = 9.94467  # in °
POSITION_LATITUDE = 53.55846  # in °
POSITION_HEIGHT = 6  # in m
OPENWEATHERMAP_API_KEY = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"


# Variables to hold the latest calculated sun position and weather forecast
sun_azimuth = shc.Variable(float, "sun_azimuth")
sun_elevation = shc.Variable(float, "sun_elevation")
weather_today_temp_max = shc.Variable(float, "weather_today_temp_max")  # in °C
weather_today_precipitation = shc.Variable(float, "weather_today_precipitation")  # in mm


# Calculate the sun's position every 5 minutes (beginning at SHC startup), using an SHC logic handler function
@shc.timer.every(datetime.timedelta(minutes=5), align=False)
@shc.handler()
async def calculate_sun_coordinates(_value, _origin):
    # The actual calculation / coordinate transformation is quite CPU-intensive.
    # To avoid blocking SHC's asyncio eventloop for the duration of the calcuation, we execute it in a
    # background thread, using asyncio's run_in_executor() method. This preemptive pseudo-parallelism, using the
    # scheduler of our operating system.
    (azimuth, elevation) = await asyncio.get_event_loop().run_in_executor(
        None, _sun_calculation, POSITION_LONGITUDE, POSITION_LATITUDE, POSITION_HEIGHT)
    # Update the Variables with the calculation result
    await sun_azimuth.write(azimuth)
    await sun_elevation.write(elevation)


def _sun_calculation(lon: float, lat: float, height: float) -> Tuple[float, float]:
    """
    Calculate the sky coordinates of the sun at the given earth location

    :param lon: Earth location longitude in degrees
    :param lat: Earth location latitude in degrees
    :param height: Earth location height in meters over the default ellipsoid
    :return: Current sky coordinates (azimuth, elevation) of the sun
    """
    import astropy.coordinates as coord
    from astropy.time import Time
    import astropy.units as u

    loc = coord.EarthLocation(lon=lon * u.deg,
                              lat=lat * u.deg,
                              height=height * u.m)
    now = Time.now()

    altaz = coord.AltAz(location=loc, obstime=now)
    sun = coord.get_sun(now)
    sun_in_the_sky = sun.transform_to(altaz)

    return sun_in_the_sky.az.value, sun_in_the_sky.alt.value


# Fetch the weather forecast once at application startup and every day at 5:00 AM and 11:00 AM
#
# Note, that OpenWeatherMap's free forecast collection limits the number of API requests to
# 1'000'000 per month = approx. 20 per minute. So, you may actually fetch the data with higher frequency.
@shc.timer.once()
@shc.timer.at(hour=[5, 11])
@shc.handler()
async def get_weather_forecast(_value, _origin):
    async with aiohttp.request('GET',
                               "https://api.openweathermap.org/data/2.5/onecall",
                               params={'lon': str(round(POSITION_LONGITUDE * 100) / 100),
                                       'lat': str(round(POSITION_LATITUDE * 100) / 100),
                                       'appid': OPENWEATHERMAP_API_KEY}) as resp:
        if resp.status != 200:
            raise ValueError(f"Could not get weather forecast. Open Weather Map answered with HTTP {resp.status}",
                             await resp.text())
        data = await resp.json()

    today = datetime.date.today()

    for day_forecast in data['daily']:
        date = datetime.datetime.utcfromtimestamp(day_forecast['dt']).date()
        if date == today:
            await weather_today_temp_max.write(day_forecast['temp']['max'] - 273.15)
            if 'rain' in day_forecast:
                await weather_today_precipitation.write(day_forecast['rain'])
            break

    # There is a lot more data in OpenWeatherMap's forecast:
    # import json
    # print(json.dumps(data, indent=4))

    # You can also do further calculations with da data: For example, in my application, I calculate the maximum
    # temperature over the next three days (to automatically decide if sunshading should be used) and the total
    # precipitation over the next two days (to decide if automated plant watering should be activated)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    shc.main()
