import io
import os
import time
import json
import uuid
import datetime
from database import database

import pydub
import requests
from flask import Flask, render_template, jsonify, request
from geojson import Feature, Point, FeatureCollection, codec

from key import key

from google.cloud import speech
from google.cloud.speech import enums
from google.cloud.speech import types
from oauth2client.client import GoogleCredentials

from wit import Wit

wit_ai_token = '3KGJYXXQKXQ7X6FQYOOSDOSFMLAEZFLZ'

application = Flask(__name__)
application.config['SEND_FILE_MAX_AGE_DEFAULT'] = 1

# all required web service URLs
search_url = "https://maps.googleapis.com/maps/api/place/textsearch/json"
photos_url = "https://maps.googleapis.com/maps/api/place/photo"
map_url = "https://maps.googleapis.com/maps/api/staticmap"
stream_url = 'http://relay.broadcastify.com:80/37813088?nocache=3792733'
geoparse_url = 'https://geoparser.io/api/geoparser'

# amount of audio to fetch on each call to scanner
max_time = 15


db = None
# Check if it is a windows machine for correct path
if os.name == 'nt':
    db = database('DB\pdscanner.db')
# Otherwise assume linux
else:
    db = database('DB/pdscanner.db')

# main application route - renders main page
@application.route("/", methods=["GET"])
def retreive():
    with open('static/asset.json', 'rb') as f:
        data = json.load(f)
        assets = json.dumps(data)

    application.logger.info(assets)

    return render_template('layout2.html', value=assets)


# primary application function to fetch scanner data and map
@application.route("/sendRequest/scanner", methods=["GET", "POST"])
def scan():
    application.logger.info('entering scanner function')

    selected_parser = request.args.get("option")
    application.logger.info('selected parser is %s' % selected_parser)

    # delete any intermediary files
    if os.path.isfile("stream.mp3"):
        os.remove("stream.mp3")
    if os.path.isfile("stream.wav"):
        os.remove("stream.wav")

    start_time = time.time()
    application.logger.info('fetch audio from stream')
    # make a calll to the police scanner audio feed
    r = requests.get(stream_url, stream=True)

    # store audio blocks in temp MP3 file
    with open('static/stream.mp3', 'wb') as f:
        try:
            for block in r.iter_content(1024):
                f.write(block)
                if (time.time() - start_time) > max_time:
                    break
        except Exception:
            pass

    # transcode the audio from MP3 to WAV for Google Speech API
    application.logger.info('trancode audio to WAV')
    sound = pydub.AudioSegment.from_mp3("static/stream.mp3")
    sound.export("static/stream.wav", format="wav")
    application.logger.info('finished transcoding audio to WAV')

    application.logger.info('transcribe audio')
    utterances, marker_coordinates = transcribe_file("static/stream.wav", sound.frame_rate, selected_parser)
    application.logger.info('finished transcribing')

    return jsonify(map_markers = marker_coordinates)

    # if there are any addresses identified
    # if bool(marker_coordinates):
    #     application.logger.info('generate map')
    #     map_request = generate_map_image(marker_coordinates)
    #     photo_type = imghdr.what("", map_request.content)
    #     photo_name = "static/" + "map" + "." + photo_type
    #
    #     with open(photo_name, "wb") as photo:
    #         photo.write(map_request.content)
    #     json_ret = jsonify(image='<img id=image1 src=' + photo_name + "?random=" + str(time.time()) + '>',
    #                        transcript=utterances, audio='static/stream.mp3?random=' + str(time.time()))
    #
    #     application.logger.info('return scanner function with map and transcript')
    #     return json_ret
    #
    # # if no addresses use static map
    # else:
    #     json_ret = jsonify(image='<img id=image1 src=' + 'static/portland1.png' + '>', transcript=utterances,
    #                        audio='static/stream.mp3?random=' + str(time.time()))
    #
    #     application.logger.info('return scanner function with generic map and transcript')
    #     return json_ret


# function to generate map
def generate_map_image(marker_coordinates):
    search_payload = {"key": key, "query": "Portland, OR"}
    search_req = requests.get(search_url, params=search_payload)
    search_json = search_req.json()
    coordinates = str(search_json["results"][0]["geometry"]["location"]["lat"]) + "," + str(
        search_json["results"][0]["geometry"]["location"]["lng"])
    map_payload = {"key": key, "size": "640x640", "zoom": 12, "center": coordinates, "type": "hybrid",
                   "markers": marker_coordinates}
    map_request = requests.get(map_url, params=map_payload)
    return map_request


# function to geo parse
def geo_parse(transcribed_text, parser):
    if parser == 'google':
        query = transcribed_text + ", " + "Portland, OR"
        search_payload = {"key": key, "query": query}
        search_req = requests.get(search_url, params=search_payload)
        search_json = search_req.json()

        if bool(search_json["results"]):
            # return lat, long adress, and raw JSON
            return str(search_json["results"][0]["geometry"]["location"]["lat"]), str(
                search_json["results"][0]["geometry"]["location"]["lng"]), \
                   search_json["results"][0]["formatted_address"], search_json
        else:
            return None, None, None, search_json
    elif parser == 'wit':
        client = Wit(wit_ai_token)
        resp = client.message(transcribed_text)

        if bool(resp["entities"]):
            query = resp["entities"]["location"][0]["value"] + ", " + "Portland, OR"
            search_payload = {"key": key, "query": query}
            search_req = requests.get(search_url, params=search_payload)
            search_json = search_req.json()

            if bool(search_json["results"]):
                # return lat, long adress, and raw JSON
                return str(search_json["results"][0]["geometry"]["location"]["lat"]), str(
                    search_json["results"][0]["geometry"]["location"]["lng"]), \
                       search_json["results"][0]["formatted_address"], search_json
            else:
                return None, None, None, search_json

        else:
            return None, None, None, resp


# function to transcribe
def transcribe_file(speech_file, sample_rate, parser):
    # authenticate with google using credentials in JSON file
    credentials = GoogleCredentials.get_application_default()

    client = speech.SpeechClient()

    # open audio file
    with io.open(speech_file, 'rb') as audio_file:
        content = audio_file.read()

    # send audio file to recognizer
    audio = types.RecognitionAudio(content=content)
    config = types.RecognitionConfig(
        encoding=enums.RecognitionConfig.AudioEncoding.LINEAR16,
        sample_rate_hertz=sample_rate,
        language_code='en-US')

    utterances = []
    marker_coordinates = []

    # send audio to recognizer
    response = client.recognize(config, audio)

    # Each result is for a consecutive portion of the audio.
    # #Iterate through them to get the transcripts for the entire audio file.
    for result in response.results:
        # The first alternative is the most likely one for this portion.
        application.logger.info('Transcript: {}'.format(result.alternatives[0].transcript))

        # send transcribed text to geo parse services_
        lat, long, address, geo_json = geo_parse(result.alternatives[0].transcript, parser)


        # if we get back any geo parse results store as markers for map and append to utterance text
        if bool(address) and lat is not None:
            my_point = Point((float(long), float(lat)))
            my_feature = Feature(geometry=my_point, properties={'title': 'Geo Location: {}'.format(address),'description': 'Transcript: {}'.format(result.alternatives[0].transcript), 'marker-size': 'large', 'marker-color': '#FF0000','marker-symbol': 'police'})

            # Insert record into DB
            row = [str(uuid.uuid4()), float(long), float(lat), 'Geo Location: {}'.format(address), 'Transcript: {}'.format(result.alternatives[0].transcript), str(datetime.datetime.now())]
            db.InsertRow(tablename='security_events', row=row)
            #use this line to temp export the table for debugging
            #db.ExportCSV(tablename='security_events')

            # store lat long as marker coordinates for map
            marker_coordinates.append(my_feature)
            # store utterance with geo parsed address after for disaply
            utterances.append('Transcript: {}'.format(result.alternatives[0].transcript) +
                              ' ( ' + '<em style="color:LightGray;">' + 'Geo Location: {}'.format(
                address) + '</em>' + ' )')

        elif bool(address) and lat is None:
            utterances.append(
                'Transcript: {}'.format(result.alternatives[0].transcript) + ' ( ' + '<em style="color:LightGray;">' +
                'Geo Location: {}'.format(address) + '</em>' + ' )')
        # if there are no geo parsed results just added text without address
        else:
            utterances.append('Transcript: {}'.format(result.alternatives[0].transcript))

    return utterances, marker_coordinates


@application.after_request
def add_header(response):
    # response.cache_control.no_store = True
    if 'Cache-Control' not in response.headers:
        response.headers['Cache-Control'] = 'no-store'
    return response


if __name__ == "__main__":
    application.run(debug=True, threaded=True)

    # def gen(r):
    #     time.sleep(10)
    #     for block in  r.iter_content(1024):
    #         if block:
    #             with open('static/stream1.mp3', 'wb') as f:
    #                 try:
    #                     f.write(block)
    #                 except Exception:
    #                     pass
    #             sound = pydub.AudioSegment.from_mp3("static/stream1.mp3")
    #             sound.export("static/stream1.wav", format="wav")
    #             sound_wav = pydub.AudioSegment.from_wav("static/stream1.wav")
    #             audio_buffer.append(sound_wav.raw_data)
    #             ret_val = transcribe_stream(sound_wav.raw_data, sound_wav.frame_rate)
    #             print(ret_val)
    #             yield block
    #
    #
    # @application.route('/scanner_feed')
    # def scanner_feed():
    #     r = requests.get(stream_url, stream=True)
    #     return Response(gen(r),
    #                     mimetype='audio/mp3')

    # def transcribe_stream(speech_buffer, sample_rate):
    #     """Transcribe the given audio file."""
    #     from google.cloud import speech
    #     from google.cloud.speech import enums
    #     from google.cloud.speech import types
    #
    #     from oauth2client.client import GoogleCredentials
    #     credentials = GoogleCredentials.get_application_default()
    #
    #     client = speech.SpeechClient()
    #
    #     #with io.open(speech_file, 'rb') as audio_file:
    #     #    content = audio_file.read()
    #
    #     audio = types.RecognitionAudio(content=speech_buffer)
    #     config = types.RecognitionConfig(
    #         encoding=enums.RecognitionConfig.AudioEncoding.LINEAR16,
    #         sample_rate_hertz=sample_rate,
    #         language_code='en-US')
    #     response = client.recognize(config, audio)
    #     for result in response.results:
    #         print('Transcript: {}'.format(result.alternatives[0].transcript))
    #         return 'Transcript: {}'.format(result.alternatives[0].transcript)
    #     return ""
    #
    #
    #     #response = client.recognize(config, audio)
    #     # Each result is for a consecutive portion of the audio. Iterate through
    #     # them to get the transcripts for the entire audio file.
    #     #utterances = []
    #     #marker_coordinates = []
    #     utts_address = dict()
    #     index = 0
    #     #for result in response.results:
    #         # The first alternative is the most likely one for this portion.
    #         #print('Transcript: {}'.format(result.alternatives[0].transcript))
    #         #utterances.append('Transcript: {}'.format(result.alternatives[0].transcript))
    #
    #         #query = result.alternatives[0].transcript + ", " + "Portland, OR"
    #         #search_payload = {"key": key, "query": query}
    #         #search_req = requests.get(search_url, params=search_payload)
    #         #search_json = search_req.json()
    #
    #         #if bool(search_json["results"]):
    #             #marker_coordinates.append(str(search_json["results"][0]["geometry"]["location"]["lat"]) + "," + str(
    #             #    search_json["results"][0]["geometry"]["location"]["lng"]))
    #             #utterances.append('Transcript: {}'.format(result.alternatives[0].transcript) + ' ( ' + '<em style="color:LightGray;">' + 'Geo Location: {}'.format(search_json["results"][0]["formatted_address"]) + '</em>' + ' )')
    #             #utts_address[utterances[index]] = marker_coordinates[index]
    #             #index = index + 1
    #
    #         #else:
    #             #utterances.append('Transcript: {}'.format(result.alternatives[0].transcript))
    #             #utts_address[utterances[index]] = None
    #             #index = index + 1
    #
    #     #if bool(marker_coordinates):
    #     #    search_payload = {"key": key, "query": "Portland, OR"}
    #     #    search_req = requests.get(search_url, params=search_payload)
    #     #    search_json = search_req.json()
    #     #    coordinates = str(search_json["results"][0]["geometry"]["location"]["lat"]) + "," + str(
    #     #        search_json["results"][0]["geometry"]["location"]["lng"])
    #     #    map_payload = {"key": key, "size": "640x640", "zoom": 12, "center": coordinates, "type": "hybrid", "markers": marker_coordinates}
    #     #    map_request = requests.get(map_url, params=map_payload)
    #
    #      #   photo_type = imghdr.what("", map_request.content)
    #      #   photo_name = "static/" + "map" + "." + photo_type
    #
    #       #  with open(photo_name, "wb") as photo:
    #       #      photo.write(map_request.content)
    #
    #       #  json_ret = jsonify(image='<img src=' + photo_name + "?random=" + str(time.time()) + '>',
    #       #                 transcript=utterances, audio='<audio id=audio1 src=' + 'static/stream.mp3?random=' + str(time.time()) + ' type=audio/mp3>')
    #       #  return 1, json_ret
    #
    #     #else:
    #     #    return 0, utterances

    # @application.route("/sendRequest/<string:query>")
    # def results(query):
    #     search_payload = {"key": key, "query": query}
    #     search_req = requests.get(search_url, params=search_payload)
    #     search_json = search_req.json()
    #
    #     coordinates = str(search_json["results"][0]["geometry"]["location"]["lat"]) + "," + str(
    #         search_json["results"][0]["geometry"]["location"]["lng"])
    #     map_payload = {"key": key, "size": "640x640", "zoom": 12, "center": coordinates, "type": hybrid}
    #     map_request = requests.get(map_url, params=map_payload)
    #
    #     photo_type = imghdr.what("", map_request.content)
    #     photo_name = "static/" + query + "." + photo_type
    #
    #     with open(photo_name, "wb") as photo:
    #         photo.write(map_request.content)
    #
    #     return '<img src=' + photo_name + '>'
