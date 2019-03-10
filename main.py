import smartcar
from flask import Flask, redirect, request, jsonify, render_template, url_for
from flask_cors import CORS
from flask_table import Table, Col
from twilio.rest import Client
from twilio.twiml.messaging_response import MessagingResponse
from twilio.twiml.voice_response import VoiceResponse, Gather
import urllib
import os
import json
import math
import polyline
import requests
import datetime

# Bryan Zhu
# HackRU Spring 2019
# SmartCar "Best Car App" challenge
# Twilio "Best use of the Twilio API" challenge
# "Best Solo Hack" challenge

# https://pypi.org/project/smartcar/
# https://developers.google.com/maps/documentation/maps-static/intro
# https://developers.google.com/maps/documentation/maps-static/dev-guide

app = Flask(__name__)
CORS(app)

# global variable to save SmartCar access_token
CLIENT_ID = ''  # CENSORED
CLIENT_SECRET = ''  # CENSORED
REDIRECT_URI = 'http://localhost:8000/exchange'
smartcar_access = None

smartcar_client = smartcar.AuthClient(
    client_id=CLIENT_ID,
    client_secret=CLIENT_SECRET,
    redirect_uri=REDIRECT_URI,
    scope=['read_vehicle_info','read_location'],
    test_mode=True
)

# earth radius in miles; units given by user should be consistent
EARTH_RADIUS = 3958.8

# Google Maps API
MAPS_API_KEY = ''  # CENSORED
MAPS_STATIC_URL_START = 'https://maps.googleapis.com/maps/api/staticmap?center='
MAPS_MARKER = '&markers='
MAP_SIZE_WIDTH = '640'  # max size for free accounts
MAP_SIZE_HEIGHT = '640'  # max size for free accounts
MAP_SIZE = ''.join(['&size=', MAP_SIZE_WIDTH, 'x', MAP_SIZE_HEIGHT])
MAP_SCALE = '&scale=2'  # max scaling for free accounts
MAP_ZOOM = '&zoom=7'
MAP_TYPE = '&maptype=roadmap'

MAPS_GEOCODE_ENDPOINT = 'https://maps.googleapis.com/maps/api/geocode/json'

# Twilio Credentials
TWILIO_SID = ''  # CENSORED
TWILIO_AUTH = ''  # CENSORED
TWILIO_NUMBER = ''  # CENSORED
TWILIO_DEFAULT_TO = ''  # CENSORED
twilio_client = Client(TWILIO_SID, TWILIO_AUTH)

# don't forget to install ngrok and update your active number webhooks once it's running
# choco install ngrok.portable
# ngrok http -host-header="localhost:8000" 8000
ngrok_url = 'https://fa0be0c9.ngrok.io'

coord_areas = [dict(
    location='Denver, CO',
    latitude=39.7392,
    longitude=-104.9903,
    radius=100.0,
    distance=EARTH_RADIUS*math.pi,
    alert='Welcome to Denver!',
    entered=False,
    tts=False
    )]

# https://flask-table.readthedocs.io/en/stable/
class CoordTable(Table):
    location = Col("Alert Location")
    latitude = Col("Latitude [degrees]")
    longitude = Col("Longitude [degrees]")
    radius = Col("Alert Radius [miles]")
    distance = Col("Distance from Vehicle [miles]")
    alert = Col("Alert Message")


@app.route('/login', methods=['GET'])
def login():
    auth_url = smartcar_client.get_auth_url()
    return redirect(auth_url)

@app.route('/exchange', methods=['GET'])
def exchange():
    code = request.args.get('code')
    # access our global variable and store our access tokens
    global smartcar_access
    # in a production app you'll want to store this in some kind of
    # persistent storage
    smartcar_access = smartcar_client.exchange_code(code)
    # return '', 200
    return redirect("/alertmap", code=200)


@app.route('/alertmap', methods=['GET', 'POST'])
def alertmap():
    global coord_areas
    if request.method == 'POST':
        if request.form.get("text_alert_location") != '':
            if request.form.get("submit") == 'Add':
                req = requests.get(url = MAPS_GEOCODE_ENDPOINT, params = {'address':request.form.get("text_alert_location"), 'key':MAPS_API_KEY})
                geocoded_location = req.json()
                try:
                    temp_radius = float(request.form.get("text_alert_radius").strip())
                except ValueError:
                    temp_radius = 50
                if request.form['tts'] == 'sms':
                    temp_tts = False
                else:
                    temp_tts = True
                if request.form.get("text_alert_message").strip() == '':
                    # temp_alert = ''.join([request.form.get("text_alert_location"), '\nYou have something you need to do here.'])
                    temp_alert = 'You have something you need to do here.'
                else:
                    # temp_alert = ''.join([request.form.get("text_alert_location"), '\n', request.form.get("text_alert_message")])
                    temp_alert = request.form.get("text_alert_message")
                coord_areas.append(dict(
                    location=request.form.get("text_alert_location"),
                    latitude=geocoded_location['results'][0]['geometry']['location']['lat'],
                    longitude=geocoded_location['results'][0]['geometry']['location']['lng'],
                    radius=temp_radius,
                    distance=EARTH_RADIUS*math.pi,
                    alert=temp_alert,
                    entered=False,
                    tts=temp_tts
                    ))
            elif request.form.get("submit") == 'Delete':
                coord_areas = [area for area in coord_areas if area['location'] != request.form.get("text_alert_location")]

    # access our global variable to retrieve our access tokens
    global access
    # the list of vehicle ids
    vehicle_ids = smartcar.get_vehicle_ids(smartcar_access['access_token'])['vehicles']
    # instantiate the first vehicle in the vehicle id list
    vehicle = smartcar.Vehicle(vehicle_ids[0], smartcar_access['access_token'])
    json_loc = vehicle.location()
    lat = json_loc['data']['latitude']
    lon = json_loc['data']['longitude']
    update_distances(lat, lon, coord_areas)
    for area in coord_areas:
        if area['entered'] == True:
            if area['tts'] == False:
                send_sms(''.join([area['location'], '\n', area['alert']]))
            else:
                send_tts(''.join([area['location'], '\n...', area['alert']]))
    coord_table = CoordTable(coord_areas)
    encoded_area_coords = circle_markers(coord_areas)  # only generate on coord change? kinda wasteful to do it each time
    str_loc = ''.join([str(lat), ',', str(lon)])
    map_static = ''.join([
        MAPS_STATIC_URL_START, str_loc,
        MAP_SIZE,
        MAP_ZOOM,
        MAP_SCALE,
        MAP_TYPE,
        MAPS_MARKER, str_loc,
        encoded_area_coords,
        '&key=', MAPS_API_KEY])
    return render_template('alertmap.html', coord_table = coord_table, map_img = map_static)


def send_sms(msg):
    message = twilio_client.messages \
        .create(
            body=''.join([msg, '\n\nPlease acknowledge or delay.']),
            from_=TWILIO_NUMBER,
            to=TWILIO_DEFAULT_TO
        )

@app.route("/sms", methods=['GET', 'POST'])
def sms():
    body = request.values.get('Body', None)
    resp = MessagingResponse()
    if len(body) < 3:
        return
    if body[0:3].lower() == 'ack':
        msg_history = twilio_client.messages.list()
        # https://docs.python.org/3/library/datetime.html#strftime-and-strptime-behavior
        # Fri, 04 Sep 2015 22:54:41 +0000
        # %a, %m %b %Y %H:%M:%S %z
        # 2019-03-10 04:33:45+00:00
        # %Y-%m-%d %H:%M:%S+00:00
        # https://dbader.org/blog/python-min-max-and-nested-lists
        most_recent_msg = max(msg_history, key=lambda m: m.date_sent if m.date_sent != None else datetime.datetime.strptime('0001-01-01 00:00:00+0000', '%Y-%m-%d %H:%M:%S%z'))
        global coord_areas
        coord_areas = [area for area in coord_areas if area['location'] != most_recent_msg.body.splitlines()[0]]
        resp.message('Alert resolved, awesome!')
    elif body[0:3].lower() == 'del':
        resp.message('Got it, maybe next time then.')
    return str(resp)


def send_tts(msg):
    # parsed_template = render_template('tts.xml', tts_text = msg)
    # with open('temp_tts.xml', 'w+') as f:
    #     f.write(parsed_template)
    preencode = {'msg':msg}
    call = twilio_client.calls.create(
        to=TWILIO_DEFAULT_TO,
        from_=TWILIO_NUMBER,
        # url=render_template('tts.xml', tts_text = msg)
        # Template(render_template('tts.xml')).stream(tts_text = msg).dump('temp_tts.xml')
        # url=''.join([ngrok_url, '/temp_tts.xml'])
        # url=''.join(['/voice?msg=', msg])
        url=''.join([ngrok_url, '/voice?', urllib.parse.urlencode(preencode)])
    )
    # resp = VoiceResponse()
    # resp.say(msg, voice='alice')
    # resp.redirect('/voice', code=307)
    # return str(resp)
    # press 1 to acknowledge, delete area
    # press 2 or hang up (no response), no change

@app.route("/voice", methods=['GET', 'POST'])
def voice():
    resp = VoiceResponse()
    if 'Digits' in request.values:
        choice = request.values['Digits']
        if choice == '1':
            # call_history = twilio_client.calls.list()
            # most_recent_call = max(call_history, key=lambda m: m.date_created if m.date_created != None else datetime.datetime.strptime('0001-01-01 00:00:00+0000', '%Y-%m-%d %H:%M:%S%z'))
            global coord_areas
            coord_areas = [area for area in coord_areas if area['location'] != request.values['msg'].splitlines()[0]]
            resp.say('Alert resolved, awesome!')
            return str(resp)
        elif choice == '2':
            resp.say('Got it, maybe next time then.')
            return str(resp)
        else:
            resp.say("Sorry, I don't understand that choice.")
            resp.pause(length=1)
    gather = Gather(num_digits=1)
    gather.say(''.join([request.values['msg'], '...To acknowledge, press 1. To delay, press 2.']))
    resp.append(gather)
    preencode = {'msg':request.values['msg']}
    resp.redirect(''.join(['/voice?', urllib.parse.urlencode(preencode)]), code=307)
    return str(resp)


def circle_marker(lat, lon, circle_radius, earth_radius, precision):
    # https://pypi.org/project/polyline/
    # https://stackoverflow.com/questions/7316963/drawing-a-circle-google-static-maps
    lat_rad = lat*math.pi/180.0
    lon_rad = lon*math.pi/180.0
    radius_rad = circle_radius/earth_radius
    lat_prefix = math.sin(lat_rad)*math.cos(radius_rad)
    lat_suffix = math.cos(lat_rad)*math.sin(radius_rad)
    circle_coord = []
    for angle in range(361):
        angle_rad = angle*math.pi/180.0;
        c_lat = math.asin(lat_prefix + lat_suffix*math.cos(angle_rad))
        c_lon = ((lon_rad + math.atan2(math.sin(angle_rad)*math.sin(radius_rad)*math.cos(lat_rad), math.cos(radius_rad) - math.sin(lat_rad)*math.sin(c_lat)))*180.0)/math.pi
        c_lat = c_lat*180.0/math.pi
        circle_coord.append((c_lat, c_lon))
    return ''.join(['&path=fillcolor:0xAA000033%7Ccolor:0xFFFFFF00%7Cenc:', polyline.encode(circle_coord, precision).replace('|', '%7C')])

def circle_markers(coord_areas):
    areas = ''
    for area in coord_areas:
        areas = ''.join([areas, circle_marker(area['latitude'], area['longitude'], area['radius'], EARTH_RADIUS, 5)])
    return areas


def coord_distance(lat1, lon1, lat2, lon2, earth_radius):
    # https://www.movable-type.co.uk/scripts/latlong.html
    # https://stackoverflow.com/questions/27928/calculate-distance-between-two-latitude-longitude-points-haversine-formula
    lat1_rad = lat1*math.pi/180.0
    lat2_rad = lat2*math.pi/180.0
    delta_lat_rad = (lat2-lat1)*math.pi/180.0
    delta_lon_rad = (lon2-lon1)*math.pi/180.0
    # a = square of half the chord length between points
    a = math.pow(math.sin(delta_lat_rad)/2, 2) + math.cos(lat1_rad)*math.cos(lat2_rad)*math.pow(math.sin(delta_lon_rad)/2, 2)
    # c = angular distance in radians
    c = 2*math.atan2(math.sqrt(a), math.sqrt(1-a))
    return earth_radius*c

def update_distances(lat, lon, coord_areas):
    for area in coord_areas:
        old_distance = area['distance']
        area['distance'] = coord_distance(area['latitude'], area['longitude'], lat, lon, EARTH_RADIUS)
        if old_distance > area['radius'] and area['distance'] < area['radius']:
            area['entered'] = True
        else:
            area['entered'] = False


if __name__ == '__main__':
    app.run(port=8000)
