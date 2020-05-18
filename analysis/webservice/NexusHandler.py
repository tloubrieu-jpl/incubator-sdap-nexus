# Licensed to the Apache Software Foundation (ASF) under one or more
# contributor license agreements.  See the NOTICE file distributed with
# this work for additional information regarding copyright ownership.
# The ASF licenses this file to You under the Apache License, Version 2.0
# (the "License"); you may not use this file except in compliance with
# the License.  You may obtain a copy of the License at
#
#   http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.


import logging
from webservice.metrics.MetricsField import NumberMetricsField, SparkAccumulatorMetricsField
from webservice.metrics.MetricsRecord import MetricsRecord
import time
import types

import numpy as np
from netCDF4 import Dataset
from nexustiles.nexustiles import NexusTileService

from webservice.webmodel import NexusProcessingException

AVAILABLE_HANDLERS = []
AVAILABLE_INITIALIZERS = []


def nexus_initializer(clazz):
    log = logging.getLogger(__name__)
    try:
        wrapper = NexusInitializerWrapper(clazz)
        log.info("Adding initializer '%s'" % wrapper.clazz())
        AVAILABLE_INITIALIZERS.append(wrapper)
    except Exception as ex:
        log.warn("Initializer '%s' failed to load (reason: %s)" % (clazz, ex.message), exc_info=True)
    return clazz


def nexus_handler(clazz):
    log = logging.getLogger(__name__)
    try:
        wrapper = AlgorithmModuleWrapper(clazz)
        log.info("Adding algorithm module '%s' with path '%s' (%s)" % (wrapper.name(), wrapper.path(), wrapper.clazz()))
        AVAILABLE_HANDLERS.append(wrapper)
    except Exception as ex:
        log.warn("Handler '%s' is invalid and will be skipped (reason: %s)" % (clazz, ex.message), exc_info=True)
    return clazz


DEFAULT_PARAMETERS_SPEC = {
    "ds": {
        "name": "Dataset",
        "type": "string",
        "description": "One or more comma-separated dataset shortnames"
    },
    "minLat": {
        "name": "Minimum Latitude",
        "type": "float",
        "description": "Minimum (Southern) bounding box Latitude"
    },
    "maxLat": {
        "name": "Maximum Latitude",
        "type": "float",
        "description": "Maximum (Northern) bounding box Latitude"
    },
    "minLon": {
        "name": "Minimum Longitude",
        "type": "float",
        "description": "Minimum (Western) bounding box Longitude"
    },
    "maxLon": {
        "name": "Maximum Longitude",
        "type": "float",
        "description": "Maximum (Eastern) bounding box Longitude"
    },
    "startTime": {
        "name": "Start Time",
        "type": "long integer",
        "description": "Starting time in milliseconds since midnight Jan. 1st, 1970 UTC"
    },
    "endTime": {
        "name": "End Time",
        "type": "long integer",
        "description": "Ending time in milliseconds since midnight Jan. 1st, 1970 UTC"
    },
    "lowPassFilter": {
        "name": "Apply Low Pass Filter",
        "type": "boolean",
        "description": "Specifies whether to apply a low pass filter on the analytics results"
    },
    "seasonalFilter": {
        "name": "Apply Seasonal Filter",
        "type": "boolean",
        "description": "Specified whether to apply a seasonal cycle filter on the analytics results"
    }
}


class NexusInitializerWrapper:
    def __init__(self, clazz):
        self.__log = logging.getLogger(__name__)
        self.__hasBeenRun = False
        self.__clazz = clazz
        self.validate()

    def validate(self):
        if "init" not in self.__clazz.__dict__ or not type(self.__clazz.__dict__["init"]) == types.FunctionType:
            raise Exception("Method 'init' has not been declared")

    def clazz(self):
        return self.__clazz

    def hasBeenRun(self):
        return self.__hasBeenRun

    def init(self, config):
        if not self.__hasBeenRun:
            self.__hasBeenRun = True
            instance = self.__clazz()
            instance.init(config)
        else:
            self.log("Initializer '%s' has already been run" % self.__clazz)


class AlgorithmModuleWrapper:
    def __init__(self, clazz):
        self.__instance = None
        self.__clazz = clazz
        self.validate()

    def validate(self):
        if "calc" not in self.__clazz.__dict__ or not type(self.__clazz.__dict__["calc"]) == types.FunctionType:
            raise Exception("Method 'calc' has not been declared")

        if "path" not in self.__clazz.__dict__:
            raise Exception("Property 'path' has not been defined")

        if "name" not in self.__clazz.__dict__:
            raise Exception("Property 'name' has not been defined")

        if "description" not in self.__clazz.__dict__:
            raise Exception("Property 'description' has not been defined")

        if "params" not in self.__clazz.__dict__:
            raise Exception("Property 'params' has not been defined")

    def clazz(self):
        return self.__clazz

    def name(self):
        return self.__clazz.name

    def path(self):
        return self.__clazz.path

    def description(self):
        return self.__clazz.description

    def params(self):
        return self.__clazz.params

    def instance(self, algorithm_config=None, sc=None):
        if "singleton" in self.__clazz.__dict__ and self.__clazz.__dict__["singleton"] is True:
            if self.__instance is None:
                self.__instance = self.__clazz()

                try:
                    self.__instance.set_config(algorithm_config)
                except AttributeError:
                    pass

                try:
                    self.__instance.set_spark_context(sc)
                except AttributeError:
                    pass

            return self.__instance
        else:
            instance = self.__clazz()

            try:
                instance.set_config(algorithm_config)
            except AttributeError:
                pass

            try:
                self.__instance.set_spark_context(sc)
            except AttributeError:
                pass
            return instance

    def isValid(self):
        try:
            self.validate()
            return True
        except Exception as ex:
            return False


class CalcHandler(object):
    def calc(self, computeOptions, **args):
        raise Exception("calc() not yet implemented")


class NexusHandler(CalcHandler):
    def __init__(self, skipCassandra=False, skipSolr=False):
        CalcHandler.__init__(self)

        self.algorithm_config = None
        self._tile_service = NexusTileService(skipCassandra, skipSolr)

    def set_config(self, algorithm_config):
        self.algorithm_config = algorithm_config

    def _mergeDicts(self, x, y):
        z = x.copy()
        z.update(y)
        return z

    def _now(self):
        millis = int(round(time.time() * 1000))
        return millis

    def _mergeDataSeries(self, resultsData, dataNum, resultsMap):

        for entry in resultsData:

            # frmtdTime = datetime.fromtimestamp(entry["time"] ).strftime("%Y-%m")
            frmtdTime = entry["time"]

            if not frmtdTime in resultsMap:
                resultsMap[frmtdTime] = []
            entry["ds"] = dataNum
            resultsMap[frmtdTime].append(entry)

    def _resultsMapToList(self, resultsMap):
        resultsList = []
        for key, value in resultsMap.iteritems():
            resultsList.append(value)

        resultsList = sorted(resultsList, key=lambda entry: entry[0]["time"])
        return resultsList

    def _mergeResults(self, resultsRaw):
        resultsMap = {}

        for i in range(0, len(resultsRaw)):
            resultsSeries = resultsRaw[i]
            resultsData = resultsSeries[0]
            self._mergeDataSeries(resultsData, i, resultsMap)

        resultsList = self._resultsMapToList(resultsMap)
        return resultsList


class SparkHandler(NexusHandler):
    class SparkJobContext(object):

        class MaxConcurrentJobsReached(Exception):
            def __init__(self, *args, **kwargs):
                Exception.__init__(self, *args, **kwargs)

        def __init__(self, job_stack):
            self.spark_job_stack = job_stack
            self.job_name = None
            self.log = logging.getLogger(__name__)

        def __enter__(self):
            try:
                self.job_name = self.spark_job_stack.pop()
                self.log.debug("Using %s" % self.job_name)
            except IndexError:
                raise SparkHandler.SparkJobContext.MaxConcurrentJobsReached()
            return self

        def __exit__(self, exc_type, exc_val, exc_tb):
            if self.job_name is not None:
                self.log.debug("Returning %s" % self.job_name)
                self.spark_job_stack.append(self.job_name)

    def __init__(self, **kwargs):
        import inspect
        NexusHandler.__init__(self, **kwargs)
        self._sc = None

        self.spark_job_stack = []

        def with_spark_job_context(calc_func):
            from functools import wraps

            @wraps(calc_func)
            def wrapped(*args, **kwargs1):
                try:
                    with SparkHandler.SparkJobContext(self.spark_job_stack) as job_context:
                        # TODO Pool and Job are forced to a 1-to-1 relationship
                        calc_func.im_self._sc.setLocalProperty("spark.scheduler.pool", job_context.job_name)
                        calc_func.im_self._sc.setJobGroup(job_context.job_name, "a spark job")
                        return calc_func(*args, **kwargs1)
                except SparkHandler.SparkJobContext.MaxConcurrentJobsReached:
                    raise NexusProcessingException(code=503,
                                                   reason="Max concurrent requests reached. Please try again later.")

            return wrapped

        for member in inspect.getmembers(self, predicate=inspect.ismethod):
            if member[0] == "calc":
                setattr(self, member[0], with_spark_job_context(member[1]))

    def set_spark_context(self, sc):
        self._sc = sc

    def set_config(self, algorithm_config):
        max_concurrent_jobs = algorithm_config.getint("spark", "maxconcurrentjobs") if algorithm_config.has_section(
            "spark") and algorithm_config.has_option("spark", "maxconcurrentjobs") else 10
        self.spark_job_stack = list(["Job %s" % x for x in xrange(1, max_concurrent_jobs + 1)])
        self.algorithm_config = algorithm_config

    def _setQueryParams(self, ds, bounds, start_time=None, end_time=None,
                        start_year=None, end_year=None, clim_month=None,
                        fill=-9999.):
        self._ds = ds
        self._minLat, self._maxLat, self._minLon, self._maxLon = bounds
        self._startTime = start_time
        self._endTime = end_time
        self._startYear = start_year
        self._endYear = end_year
        self._climMonth = clim_month
        self._fill = fill

    def _set_info_from_tile_set(self, nexus_tiles):
        ntiles = len(nexus_tiles)
        self.log.debug('Attempting to extract info from {0} tiles'. \
                       format(ntiles))
        status = False
        self._latRes = None
        self._lonRes = None
        for tile in nexus_tiles:
            self.log.debug('tile coords:')
            self.log.debug('tile lats: {0}'.format(tile.latitudes))
            self.log.debug('tile lons: {0}'.format(tile.longitudes))
            if self._latRes is None:
                lats = tile.latitudes.data
                if (len(lats) > 1):
                    self._latRes = abs(lats[1] - lats[0])
            if self._lonRes is None:
                lons = tile.longitudes.data
                if (len(lons) > 1):
                    self._lonRes = abs(lons[1] - lons[0])
            if ((self._latRes is not None) and
                    (self._lonRes is not None)):
                lats_agg = np.concatenate([tile.latitudes.compressed()
                                           for tile in nexus_tiles])
                lons_agg = np.concatenate([tile.longitudes.compressed()
                                           for tile in nexus_tiles])
                self._minLatCent = np.min(lats_agg)
                self._maxLatCent = np.max(lats_agg)
                self._minLonCent = np.min(lons_agg)
                self._maxLonCent = np.max(lons_agg)
                self._nlats = int((self._maxLatCent - self._minLatCent) /
                                  self._latRes + 0.5) + 1
                self._nlons = int((self._maxLonCent - self._minLonCent) /
                                  self._lonRes + 0.5) + 1
                status = True
                break
        return status

    def _find_global_tile_set(self, metrics_callback=None):
        # This only works for a single dataset.  If more than one is provided,
        # we use the first one and ignore the rest.
        if type(self._ds) in (list, tuple):
            ds = self._ds[0]
        else:
            ds = self._ds

        # See what time stamps are in the specified range.
        t_in_range = self._tile_service.find_days_in_range_asc(self._minLat,
                                                               self._maxLat,
                                                               self._minLon,
                                                               self._maxLon,
                                                               ds,
                                                               self._startTime,
                                                               self._endTime,
                                                               metrics_callback=metrics_callback)

        # Empty tile set will be returned upon failure to find the global
        # tile set.
        nexus_tiles = []

        # Check one time stamp at a time and attempt to extract the global
        # tile set.
        for t in t_in_range:
            nexus_tiles = self._tile_service.get_tiles_bounded_by_box(self._minLat, self._maxLat, self._minLon,
                                                                      self._maxLon, ds=ds, start_time=t, end_time=t,
                                                                      metrics_callback=metrics_callback)
            if self._set_info_from_tile_set(nexus_tiles):
                # Successfully retrieved global tile set from nexus_tiles,
                # so no need to check any other time stamps.
                break
        return nexus_tiles

    def _find_tile_bounds(self, t):
        lats = t.latitudes
        lons = t.longitudes
        if (len(lats.compressed()) > 0) and (len(lons.compressed()) > 0):
            min_lat = np.ma.min(lats)
            max_lat = np.ma.max(lats)
            min_lon = np.ma.min(lons)
            max_lon = np.ma.max(lons)
            good_inds_lat = np.where(lats.mask == False)[0]
            good_inds_lon = np.where(lons.mask == False)[0]
            min_y = np.min(good_inds_lat)
            max_y = np.max(good_inds_lat)
            min_x = np.min(good_inds_lon)
            max_x = np.max(good_inds_lon)
            bounds = (min_lat, max_lat, min_lon, max_lon,
                      min_y, max_y, min_x, max_x)
        else:
            self.log.warn('Nothing in this tile!')
            bounds = None
        return bounds

    @staticmethod
    def query_by_parts(tile_service, min_lat, max_lat, min_lon, max_lon,
                       dataset, start_time, end_time, part_dim=0):
        nexus_max_tiles_per_query = 100
        # print 'trying query: ',min_lat, max_lat, min_lon, max_lon, \
        #    dataset, start_time, end_time
        try:
            tiles = \
                tile_service.find_tiles_in_box(min_lat, max_lat,
                                               min_lon, max_lon,
                                               dataset,
                                               start_time=start_time,
                                               end_time=end_time,
                                               fetch_data=False)
            assert (len(tiles) <= nexus_max_tiles_per_query)
        except:
            # print 'failed query: ',min_lat, max_lat, min_lon, max_lon, \
            #    dataset, start_time, end_time
            if part_dim == 0:
                # Partition by latitude.
                mid_lat = (min_lat + max_lat) / 2
                nexus_tiles = SparkHandler.query_by_parts(tile_service,
                                                          min_lat, mid_lat,
                                                          min_lon, max_lon,
                                                          dataset,
                                                          start_time, end_time,
                                                          part_dim=part_dim)
                nexus_tiles.extend(SparkHandler.query_by_parts(tile_service,
                                                               mid_lat,
                                                               max_lat,
                                                               min_lon,
                                                               max_lon,
                                                               dataset,
                                                               start_time,
                                                               end_time,
                                                               part_dim=part_dim))
            elif part_dim == 1:
                # Partition by longitude.
                mid_lon = (min_lon + max_lon) / 2
                nexus_tiles = SparkHandler.query_by_parts(tile_service,
                                                          min_lat, max_lat,
                                                          min_lon, mid_lon,
                                                          dataset,
                                                          start_time, end_time,
                                                          part_dim=part_dim)
                nexus_tiles.extend(SparkHandler.query_by_parts(tile_service,
                                                               min_lat,
                                                               max_lat,
                                                               mid_lon,
                                                               max_lon,
                                                               dataset,
                                                               start_time,
                                                               end_time,
                                                               part_dim=part_dim))
            elif part_dim == 2:
                # Partition by time.
                mid_time = (start_time + end_time) / 2
                nexus_tiles = SparkHandler.query_by_parts(tile_service,
                                                          min_lat, max_lat,
                                                          min_lon, max_lon,
                                                          dataset,
                                                          start_time, mid_time,
                                                          part_dim=part_dim)
                nexus_tiles.extend(SparkHandler.query_by_parts(tile_service,
                                                               min_lat,
                                                               max_lat,
                                                               min_lon,
                                                               max_lon,
                                                               dataset,
                                                               mid_time,
                                                               end_time,
                                                               part_dim=part_dim))
        else:
            # No exception, so query Cassandra for the tile data.
            # print 'Making NEXUS query to Cassandra for %d tiles...' % \
            #    len(tiles)
            # t1 = time.time()
            # print 'NEXUS call start at time %f' % t1
            # sys.stdout.flush()
            nexus_tiles = list(tile_service.fetch_data_for_tiles(*tiles))
            nexus_tiles = list(tile_service.mask_tiles_to_bbox(min_lat, max_lat,
                                                               min_lon, max_lon,
                                                               nexus_tiles))
            # t2 = time.time()
            # print 'NEXUS call end at time %f' % t2
            # print 'Seconds in NEXUS call: ', t2-t1
            # sys.stdout.flush()

        # print 'Returning %d tiles' % len(nexus_tiles)
        return nexus_tiles

    @staticmethod
    def _prune_tiles(nexus_tiles):
        del_ind = np.where([np.all(tile.data.mask) for tile in nexus_tiles])[0]
        for i in np.flipud(del_ind):
            del nexus_tiles[i]

    def _lat2ind(self, lat):
        return int((lat - self._minLatCent) / self._latRes + 0.5)

    def _lon2ind(self, lon):
        return int((lon - self._minLonCent) / self._lonRes + 0.5)

    def _ind2lat(self, y):
        return self._minLatCent + y * self._latRes

    def _ind2lon(self, x):
        return self._minLonCent + x * self._lonRes

    def _create_nc_file_time1d(self, a, fname, varname, varunits=None,
                               fill=None):
        self.log.debug('a={0}'.format(a))
        self.log.debug('shape a = {0}'.format(a.shape))
        assert len(a.shape) == 1
        time_dim = len(a)
        rootgrp = Dataset(fname, "w", format="NETCDF4")
        rootgrp.createDimension("time", time_dim)
        vals = rootgrp.createVariable(varname, "f4", dimensions=("time",),
                                      fill_value=fill)
        times = rootgrp.createVariable("time", "f4", dimensions=("time",))
        vals[:] = [d['mean'] for d in a]
        times[:] = [d['time'] for d in a]
        if varunits is not None:
            vals.units = varunits
        times.units = 'seconds since 1970-01-01 00:00:00'
        rootgrp.close()

    def _create_nc_file_latlon2d(self, a, fname, varname, varunits=None,
                                 fill=None):
        self.log.debug('a={0}'.format(a))
        self.log.debug('shape a = {0}'.format(a.shape))
        assert len(a.shape) == 2
        lat_dim, lon_dim = a.shape
        rootgrp = Dataset(fname, "w", format="NETCDF4")
        rootgrp.createDimension("lat", lat_dim)
        rootgrp.createDimension("lon", lon_dim)
        vals = rootgrp.createVariable(varname, "f4",
                                      dimensions=("lat", "lon",),
                                      fill_value=fill)
        lats = rootgrp.createVariable("lat", "f4", dimensions=("lat",))
        lons = rootgrp.createVariable("lon", "f4", dimensions=("lon",))
        vals[:, :] = a
        lats[:] = np.linspace(self._minLatCent,
                              self._maxLatCent, lat_dim)
        lons[:] = np.linspace(self._minLonCent,
                              self._maxLonCent, lon_dim)
        if varunits is not None:
            vals.units = varunits
        lats.units = "degrees north"
        lons.units = "degrees east"
        rootgrp.close()

    def _create_nc_file(self, a, fname, varname, **kwargs):
        self._create_nc_file_latlon2d(a, fname, varname, **kwargs)

    def _spark_nparts(self, nparts_requested):
        max_parallelism = 128
        num_partitions = min(nparts_requested if nparts_requested > 0
                             else self._sc.defaultParallelism,
                             max_parallelism)
        return num_partitions

    def _create_metrics_record(self):
        return MetricsRecord([
            SparkAccumulatorMetricsField(key='num_tiles',
                                         description='Number of tiles fetched',
                                         accumulator=self._sc.accumulator(0)),
            SparkAccumulatorMetricsField(key='partitions',
                                         description='Number of non-empty Spark partitions',
                                         accumulator=self._sc.accumulator(0)),
            SparkAccumulatorMetricsField(key='cassandra',
                                         description='Cumulative time to fetch data from Cassandra',
                                         accumulator=self._sc.accumulator(0)),
            SparkAccumulatorMetricsField(key='solr',
                                         description='Cumulative time to fetch data from Solr',
                                         accumulator=self._sc.accumulator(0)),
            SparkAccumulatorMetricsField(key='calculation',
                                         description='Cumulative time to do calculations',
                                         accumulator=self._sc.accumulator(0)),
            NumberMetricsField(key="actual_time", description="Total (actual) time")
        ])


def executeInitializers(config):
    [wrapper.init(config) for wrapper in AVAILABLE_INITIALIZERS]
