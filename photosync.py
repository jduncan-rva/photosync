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
        logging.basicConfig(filename=logfile, 
                level=logging.DEBUG)
        self.log = logging.getLogger(__name__)
        self._loadConfig()

    def _loadConfig(self, configfile='.config'):
        """Loads a config file"""

        self.config = configparser.ConfigParser()
        self.log.info("Loading Config File - %s", configfile)
        self.config.read(configfile)

        if 'plex' in self.config.sections():
            self.log.info("Loading Plex Configs")
            self.plexUrl = self.config['plex']['url']
            self.plexToken = self.config['plex']['token']

        if 'filesystem' in self.config.sections():
            self.log.info("Loading Filesystem Configs")
            self.dataVolume = self.config['filesystem']['data_volume']

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

    def processScannedPhotos(self, data):
        """ When creating a JSON file for scanned photos, there are some small differences, primarily around the date. We'll handle those here."""

        try:
            for pic in data:
                taken_at = pic['taken_at']
                caption = pic['caption']
                filename = pic['path']

                if os.path.exists(filename):
                    self.log.info("Processing photo - %s", filename)

                    # This adds the date and caption info to the image file
                    exif_dict = piexif.load(filename)
                    exif_dict['0th'][piexif.ImageIFD.DateTime] = taken_at
                    exif_dict['Exif'][piexif.ExifIFD.DateTimeOriginal] = taken_at
                    exif_dict['Exif'][piexif.ExifIFD.DateTimeDigitized] = taken_at
                    exif_dict['0th'][piexif.ImageIFD.ImageDescription] = caption
                    exif_dict['0th'][piexif.ImageIFD.Make] = 'Scanned Photo'    
                    exif_bytes = piexif.dump(exif_dict)
                    piexif.insert(exif_bytes, filename)    

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

            filename = pic['path']
            if os.path.exists(filename):
                self.log.info("Processing %s" % filename)

                exif_dict = piexif.load(filename)
                exif_dict['0th'][piexif.ImageIFD.DateTime] = taken_at
                exif_dict['Exif'][piexif.ExifIFD.DateTimeOriginal] = taken_at
                exif_dict['Exif'][piexif.ExifIFD.DateTimeDigitized] = taken_at
                exif_dict['0th'][piexif.ImageIFD.ImageDescription] = caption
                exif_dict['0th'][piexif.ImageIFD.Make] = 'Instagram'    
                exif_bytes = piexif.dump(exif_dict)
                piexif.insert(exif_bytes, filename)

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

    def copyFilesFromJSON(self, data, dest_dir):
        """Returns a list of all files we've got in their mounted form data is the full dataset from a JSON file. The files are copied to a temporary directory to make them easier to copy to Google Photos or other sources. This is useful when you've already added files to a library and are backfilling information"""


        for pic in data['photos']:
            #TODO make the data path a variable
            filename = os.path.join('/Volumes', pic['path'])
            filename = pic['path']
            if os.path.exists(filename):
                f = os.path.basename(filename)
                dst = os.path.join(dest_dir, f)

                print("copying ", filename)
                copyfile(filename, dst)

        if 'videos' in data.keys():
            for video in data['videos']:
                path = re.sub('videos','photos',video['path'])
                path = os.path.join('/Volumes', path)
                if os.path.exists(path):
                    f = os.path.basename(path)
                    dst = os.path.join(dest_dir, f)

                    print("copying ", path)
                    copyfile(path, dst)

    def convertCSVtoJSON(self, filename):
        """TODO This needs a lot of work to be more universal"""

        data = dict()
        data['photos'] = list()

        fh = open(filename,'r', encoding='utf-8') 
        csv_data = csv.DictReader(fh)
        for row in csv_data:
            x = dict()
            file_string = "/Volumes/photos/%s.jpg" % row['name']

            date_string = "%s 12:00:00" % row['taken_at']
            date_raw = datetime.strptime(date_string, '%m/%d/%Y %H:%M:%S')
            date_final = date_raw.strftime("%Y:%m:%d %H:%M:%S")

            caption = row['caption']

            x['caption'] = caption
            x['taken_at'] = date_final
            x['path'] = file_string

            data['photos'].append(x)

        fh.close()

        json_file = open('photo-data.json','w+',encoding='utf-8')
        json_file.write(json.dumps(data, indent=4))

        json_file.close()










