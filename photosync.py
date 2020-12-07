# Copyright 2020 Jamie Duncan

#    Licensed under the Apache License, Version 2.0 (the "License");
#    you may not use this file except in compliance with the License.
#    You may obtain a copy of the License at

#        http://www.apache.org/licenses/LICENSE-2.0

#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS,
#    WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#    See the License for the specific language governing permissions and
#    limitations under the License.

from datetime import datetime, timezone
import json
import os
import re
import csv
import subprocess
import logging
import configparser
import piexif
from shutil import copyfile
from plexapi.server import PlexServer

class photoSync:
    """A class to handle the loading of photo metadata more easily into photos (JPG) and videos (MP4 and others)"""

    def __init__(self):
        logfile = 'photosync.log'
        logging.basicConfig(filename=logfile, level=logging.DEBUG)
        self.log = logging.getLogger(__name__)
        self._loadConfig()

    def _loadConfig(self, configfile='.config'):
        """Loads a config file"""

        if os.path.exists(configfile):
            self.config = configparser.ConfigParser()
            self.log.info("Loading Config File - %s", configfile)
            self.config.read(configfile)

            if 'general' in self.config.sections():
                self.artist = self.config['general']['artist']
                self.source = self.config['general']['source']

            if 'plex' in self.config.sections():
                self.log.info("Loading Plex Configs")
                plexUrl = self.config['plex']['url']
                plexToken = self.config['plex']['token']

                self.plex = self.connectToPlex(url=plexUrl, token=plexToken)

            if 'filesystem' in self.config.sections():
                self.log.info("Loading Filesystem Configs")
                self.dataVolume = self.config['filesystem']['data_volume']
                self.copyVolume = self.config['filesystem']['copy_volume']
        else:
            self.log.info("Config File Not Found - %s", configfile)

    def loadJSON(self, filename):
        """ Returns the json data from an Instagram-style data file """

        try:
            self.log.info("Loading JSON data - %s", filename)
            fh = open(filename,'r', encoding="latin-1")
            data = json.load(fh)
            fh.close()
            self.log.info("JSON data successfully loaded - %s", filename)

            return data
        except Exception as e:
            self.log.error(e)
            raise e

    def _processPhoto(self, filename, caption, taken_at):   
        """This function does the heavy lifting of actually editing the metadata tag for a jpg image"""

        try:
            self.log.info("Processing photo - %s", filename)

            # This adds the date and caption info to the image 
            # file in the proper locations 
            cmd = [
                'exiftool',
                '-overwrite_original',
                '-iptc:Caption-Abstract=%s' % caption,
                '-iptc:Headline=%s' % caption,
                '-exif:imagedescription=%s' % caption,
                '-AllDates=%s'% taken_at,
                '-make=%s' % self.source,
                '-artist=%s' % self.artist,
                filename
            ]
            subprocess.run(cmd)

        except Exception as e:
            self.log.error(e)
            raise e


    def processScannedPhotos(self, data):
        """ When creating a JSON file for scanned photos, there are some small differences, primarily around the date. We'll handle those here."""

        try:
            for pic in data:
                taken_at = pic['taken_at']
                caption = pic['caption']
                filename = pic['path']

                if os.path.exists(filename):
                    self._processPhoto(filename=filename, 
                                        taken_at=taken_at, 
                                        caption=caption)

        except Exception as e:
            self.log.error(e)
            raise(e)


    def processIGPhotos(self, data):
        """ Processes photo information in an IG-style data file """

        # data is the 'photos' list from the JSON file
        for pic in data['photos']:

            # get the date and fix the timezone to the one running on your 
            # system. This isn't a perfect fix, but it should be closer for
            # anyone who isn't a massive world traveler
            raw_date = datetime.fromisoformat(pic['taken_at'])
            d = raw_date.replace(tzinfo=timezone.utc).astimezone(tz=None)
            taken_at = d.strftime("%Y:%m:%d %H:%M:%S")
        
            if 'location' in pic.keys():
                caption = "%s - %s" % (str(pic['caption']),str(pic['location']))

            else:
                caption = str(pic['caption'])

            filename = os.path.join(self.dataVolume, pic['path'])
            if os.path.exists(filename):
                self._processPhoto(filename=filename, 
                                    taken_at=taken_at, 
                                    caption=caption)

    def processIGVideos(self, data):
        """ Processes video information (date only) for IG-style data file. It has a dependency on exiftool (https://exiftool.org/) to edit the creation date in a video file. exiftool understands how to manipulate this for most formats, but I've only tested it on mp4's from an IG export."""

        # data is a is the 'videos' list from the IG JSON file
        for video in data:
            raw_date = datetime.fromisoformat(video['taken_at'])
            d = raw_date.replace(tzinfo=timezone.utc).astimezone(tz=None)
            taken_at = d.strftime("%Y:%m:%d %H:%M:%S")

            filename = re.sub('videos','photos',video['path'])
            filename = os.path.join('/Volumes', video['path'])

            cmd = [
                'exiftool',
                "-CreateDate=%s" % taken_at,
                filename
            ]

            subprocess.run(cmd)

    def connectToPlex(self, token, url):
        """Returns a Plex connection object"""
        plex = PlexServer(url, token)

        return plex

    def copyFilesFromJSON(self, data):
        """Returns a list of all files we've got in their mounted form data is the full dataset from a JSON file. The files are copied to a temporary directory to make them easier to copy to Google Photos or other sources. This is useful when you've already added files to a library and are backfilling information"""


        for pic in data['photos']:
            filename = os.path.join(self.dataVolume, pic['path'])
            if os.path.exists(filename):
                f = os.path.basename(filename)
                dst = os.path.join(self.copyVolume, f)

                self.log.info("Copying File - %s", filename)
                copyfile(filename, dst)

        if 'videos' in data.keys():
            for video in data['videos']:
                path = re.sub('videos','photos',video['path'])
                path = os.path.join(self.dataVolume, path)
                if os.path.exists(path):
                    f = os.path.basename(path)
                    dst = os.path.join(self.copyVolume, f)

                    print("copying ", path)
                    copyfile(path, dst)

    def convertCSVtoJSON(self, filename):
        """TODO This needs a lot of work to be more universal"""

        data = dict()
        data['photos'] = list()

        self.log.info("Processing CSV File - %s", filename)
        fh = open(filename,'r', encoding='utf-8') 
        csv_data = csv.DictReader(fh)
        for row in csv_data:
            x = dict()
            file_string = "%s/%s.jpg" % (self.dataVolume, row['name'])

            date_string = "%s 12:00:00" % row['taken_at']
            date_raw = datetime.strptime(date_string, '%m/%d/%Y %H:%M:%S')
            date_final = date_raw.strftime("%Y:%m:%d %H:%M:%S")

            caption = row['caption']

            x['caption'] = caption
            x['taken_at'] = date_final
            x['path'] = file_string

            self.log.debug("Adding Path - %s", x['path'])
            data['photos'].append(x)

        fh.close()

        json_filename = re.sub('.csv','.json',filename)
        self.log.info("Creating JSON File - %s", json_filename)
        json_file = open(json_filename,'w+',encoding='utf-8')
        json_file.write(json.dumps(data, indent=4))

        json_file.close()

        return json_filename










