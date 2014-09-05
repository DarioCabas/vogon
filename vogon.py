#!/usr/bin/python
# vim: set fileencoding=utf-8 :

"""Vogon: scalable customization of video campaigns.

Vogon combines a video creative, a data table and a layout specification,
generating a copy of the video creative combined with each line of the data
table according to the layout specification.

The data can contain text and images. The specification determines the timing,
position and font definitions for each piece of text and image, referencing
data fields through their names. Fixed text can also be used in the layout
specification.
"""

import argparse
import subprocess
import tempfile
import os
import itertools
import re

import csv
import json

import yt_upload
from oauth2client.tools import argparser
from apiclient.errors import HttpError

def generate_videos(config_file, youtube_upload, preview_line, flags):
    """Generate custom videos according to the given configuration file name.

    The configuration file (JSON) is interpreted, and the specified video input
    is combined with the data in the specified data file (CSV) to generate an
    output video for each line in the data file.
    """
    config = load_config(config_file)
    data = read_csv_file(config['data_file'], ',')
    if preview_line is not None:
        lines = [[(preview_line - 1), data[preview_line - 1]]]
    else:
        lines = enumerate(data)
    for i, row in lines:
        video = generate_video(config, row, (i + 1))
        if youtube_upload:
            title = replace_vars(config['video_title'], row)
            description = replace_vars(config['video_description'], row)
            upload_to_youtube(video, title, description, flags)

def generate_video(config, row, row_num):
    row['$id'] = str(row_num)
    image_overlays = replace_vars_in_overlay(config['images'], row)
    text_overlays = replace_vars_in_overlay(config['text_lines'], row)
    img_args = image_inputs(image_overlays)
    filters = filter_strings(image_overlays, text_overlays)
    output_video = replace_vars(config['output_video'], row)
    run_ffmpeg(img_args, filters, config['video'], output_video)
    return output_video

def filter_strings(images, text_lines):
    """Generate a complex filter specification for ffmpeg.

    Arguments:
    images -- a list of image overlay objects
    text_lines -- a list of text overlay objects
    """
    retval = []
    overlays = (images + text_lines)
    input_stream = '0:v'
    for i, ovr in enumerate(overlays):
        output_stream = None if i == (len(overlays) - 1) else ('str' + str(i))
        if 'image' in ovr:
            f = image_filter(input_stream, (i+1), ovr['x'], ovr['y'],
                             ovr['start_time'], ovr['end_time'], output_stream)
        else:
            f = text_filter(input_stream, ovr['text'], ovr['font'],
                            ovr['font_size'], ovr['font_color'], ovr['x'],
                            ovr['y'], ovr['start_time'], ovr['end_time'],
                            output_stream)
        retval.append(f)
        input_stream = output_stream
    return retval

def run_ffmpeg(img_args, filters, input_video, output_video):
    """Run the ffmpeg executable for the given input and filter spec.

    Arguments:
    img_args -- a list of '-i' input arguments for the images
    filters -- complex filter specification
    input_video -- main input video file name
    output_video -- output video file name
    """
    args = (['ffmpeg', '-y', '-i', input_video] + img_args +
            ['-filter_complex', ';'.join(filters), output_video])
    subprocess.call(args)

def image_inputs(images):
    """Generate a list of input arguments for ffmpeg with the given images."""
    return list(itertools.chain(*[('-i', img['image']) for img in images]))

def image_filter(input_stream, image_stream_index, x, y, t_start, t_end,
                 output_stream):
    """Generate a ffmeg filter specification for an image input.

    Arguments:
    input_stream -- name of the input stream
    image_stream_index -- index of the input image among the -i arguments
    x, y -- position where to overlay the image on the video
    t_start, t_end -- start and end time of the image's appearance
    output_stream -- name of the output stream
    """
    out_str = '' if output_stream is None else ('[' + output_stream + ']')
    return ('[' + input_stream + '][' + str(image_stream_index) + ':v] '
            'overlay=' + str(x) + ':' + str(y) + ':'
            'enable=\'between(t,' + str(t_start) + ','
                + str(t_end) + ')\' ' +
            out_str)

def text_filter(input_stream, text, font, font_size, font_color, x, y, t_start,
                t_end, output_stream):
    """Generate a ffmeg filter specification for a text overlay.

    Arguments:
    input_stream -- name of the input stream
    text -- the text to overlay on the video
    font -- the file name of the font to be used
    font_size, font_color -- font specifications
    x, y -- position where to overlay the image on the video
    t_start, t_end -- start and end time of the image's appearance
    output_stream -- name of the output stream
    """
    # Write the text to a file to avoid the special character escaping mess
    text_file_name = write_to_temp_file(text)
    out_str = '' if output_stream is None else ('['+output_stream+']')
    return ('[' + input_stream + '] '
            'drawtext=fontfile=' + font + ':'
            'textfile=' + text_file_name + ':'
            'fontsize=' + str(font_size) + ':'
            'fontcolor=' + font_color + ':'
            'x=' + str(x) + ':y=' + str(y) + ':'
            'enable=\'between(t,' + str(t_start) + ','
                + str(t_end) + ')\' ' +
            out_str)

def write_to_temp_file(text):
    """Write a string to a new temporary file and return its name."""
    (fd, text_file_name) = tempfile.mkstemp(prefix='vogon_', suffix='.txt',
                                            text=True)
    with os.fdopen(fd, 'w') as f:
        f.write(text.encode('utf8'))
    return text_file_name

def load_config(config_file_name):
    """Load the JSON configuration file and return its structure."""
    with open(config_file_name, 'r') as f:
        retval = json.load(f)
    return retval

def test_read_csv_file():
    print read_csv_file('sample.csv', ',')

def read_csv_file(file_name, delimiter):
    """Read a CSV file and return a list of the records in it.

    Return a list of dictionaries. The keys for each dict are taken from the
    first line of the CSV, which is considered the header.

    Arguments:
    file_name -- CSV file name
    delimiter -- character to be used as column delimiter
    """
    retval = []
    with open(file_name, 'r') as f:
        data = csv.reader(f, delimiter=delimiter, quotechar='"')
        header_row = data.next()
        header = [unicode(h, 'utf8') for h in header_row]
        for row in data:
            item = {}
            for (i, value) in enumerate(row):
                item[header[i]] = unicode(value, 'utf8')
            retval.append(item)
    return retval

def test_replace_vars():
    config = load_config('sample.json')
    data = read_csv_file(config['data_file'],',')
    for row in data:
        print replace_vars_in_overlay(config['images'], row)
        print replace_vars_in_overlay(config['text_lines'], row)

def replace_vars_in_overlay(overlay_configs, values):
    """Replace all occurrences of variables in the configs with the values."""
    retval = []
    for o in overlay_configs:
        row = {}
        for c_key, c_value in o.iteritems():
            if isinstance(c_value, basestring):
                row[c_key] = replace_vars(c_value, values)
            else:
                row[c_key] = c_value
        retval.append(row)
    return retval

def replace_vars(s, values):
    """Replace all occurrences of variables in the given string with values"""
    retval = s
    for v_key, v_value in values.iteritems():
        replace = re.compile(re.escape('{{' + v_key + '}}'), re.IGNORECASE)
        retval = re.sub(replace, v_value, retval)
        #value = value.replace('{{' + v_key.lower() + '}}', v_value)
    return retval

def upload_to_youtube(video, title, description, flags):
    flags.file = video
    flags.title = title
    flags.description = description
    flags.keywords = "" #TODO add video keywords config
    flags.category = 22 #TODO add video category config
    flags.privacyStatus = 'private' #TODO add video privacy config
    flags.noauth_local_webserver = True
    youtube = yt_upload.get_authenticated_service(flags)
    try:
        yt_upload.initialize_upload(youtube, flags)
    except HttpError, e:
        print "An HTTP error %d occurred:\n%s" % (e.resp.status, e.content)

def main():
    parser = argparse.ArgumentParser(parents=[argparser])
    parser.add_argument("config_file", help="Configuration JSON file")
    parser.add_argument("--youtube_upload",
            help="Upload generated videos to YouTube",
            action="store_true")
    parser.add_argument("--preview_line",
            help="Generate only one video, for the given CSV line number",
            type=int,
            default=1)
    args = parser.parse_args()
    generate_videos(args.config_file, args.youtube_upload, args.preview_line, args)

if __name__=='__main__':
    main()
