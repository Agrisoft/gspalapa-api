#!/usr/bin/env python

# Basic PALAPA Module
# v.03
# --------
# Initial version, using GeoServer plain password, as GeoServer hash is ... :P
#
# tejo
# August 2016

import os, sys
import sys, os
# abspath = os.path.dirname(__file__)
# sys.path.append(abspath)
# os.chdir(abspath)
import urllib2, json, base64, sqlalchemy, sqlalchemy_utils, zipfile, ogr, shapefile, psycopg2, uuid, jwt, datetime, re
import ogr2ogr, osr, re, gdal, xmltodict
from flask import Flask, abort, request, redirect, jsonify, g, url_for, send_from_directory, Response, stream_with_context
from flask_jwt import JWT, jwt_required, current_identity
from werkzeug import secure_filename
from flask_sqlalchemy import SQLAlchemy
from flask_security import http_auth_required, auth_token_required, Security, RoleMixin, UserMixin, SQLAlchemyUserDatastore
from sqlalchemy import create_engine
from sqlalchemy.sql import func
import psycopg2
from psycopg2.extensions import ISOLATION_LEVEL_AUTOCOMMIT
from flask_httpauth import HTTPBasicAuth
from flask_cors import CORS, cross_origin
from passlib.apps import custom_app_context as pwd_context
from itsdangerous import (TimedJSONWebSignatureSerializer as Serializer, BadSignature, SignatureExpired)
from flask_marshmallow import Marshmallow
from geoserver.catalog import Catalog
from urllib2 import unquote
from owslib.csw import CatalogueServiceWeb
from owslib.wms import WebMapService
from shutil import copyfile
from big_parser import parse_big_md
from pygeometa import render_template

# initialization
app = Flask(__name__)
app.config['SECURITY_TRACKABLE'] = True
app.config['SECURITY_PASSWORD_HASH'] = 'pbkdf2_sha512'
app.config['SECURITY_PASSWORD_SALT'] = 'PALAPA_ini_PALAPA_ini_PALAPA_ini_PALAPA'
app.config['WTF_CSRF_ENABLED'] = False
app.config['SECURITY_TOKEN_MAX_AGE'] = 365*24*60*60*1000
app.config['SECRET_KEY'] = 'PALAPA ini PALAPA ini PALAPA ini PALAPA'
app.config['SQLALCHEMY_DATABASE_URI'] = 'postgres://palapa:palapa@192.168.198.133/palapa'
app.config['SQLALCHEMY_BINDS'] = {
    'dbdev': 'postgres://palapa:palapa@192.168.198.133/palapa_dev',
    'dbprod': 'postgres://palapa:palapa@192.168.198.133/palapa_prod',
    'dbpub': 'postgres://palapa:palapa@192.168.198.133/palapa_pub',
    'services': 'postgres://palapa:palapa@192.168.198.133/palapa'
}
app.config['SQLALCHEMY_COMMIT_ON_TEARDOWN'] = True
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = True
app.config['SQLALCHEMY_DATASTORE'] = 'postgres://palapa:palapa@192.168.198.133/'
app.config['GEOSERVER_REST_URL'] = 'http://192.168.198.133:8080/geoserver/rest/'
app.config['GEOSERVER_WMS_URL'] = 'http://192.168.198.133:8080/geoserver/wms?'
app.config['GEOSERVER_WFS_URL'] = 'http://192.168.198.133:8080/geoserver/wfs?'
app.config['GEOSERVER_USER'] = 'palapa'
app.config['GEOSERVER_PASS'] = 'palapa'
app.config['GEOSERVER_THUMBNAILS'] = '/var/www/html/assets/thumbnails/'
app.config['GEOSERVER_LAYERS_PROP'] = '/cygdrive/d/TEMP/security/layers.properties'
app.config['DATASTORE_HOST'] = '192.168.198.133'
app.config['DATASTORE_PORT'] = '5432'
app.config['DATASTORE_USER'] = 'palapa'
app.config['DATASTORE_PASS'] = 'palapa'
app.config['DATASTORE_DB'] = 'palapa'
app.config['UPLOAD_FOLDER'] = '/cygdrive/d/Workspaces/DEV/gs-api/uploads/'
app.config['RASTER_FOLDER'] = '/cygdrive/d/Workspaces/DEV/gs-api/data/'
app.config['RASTER_STORE'] = '/mnt/store/'
app.config['ALLOWED_EXTENSIONS'] = set(['zip','ZIP'])
app.config['ALLOWED_VECTOR'] = set(['shp','SHP'])
app.config['ALLOWED_RASTER'] = set(['tiff','tif','TIF','TIFF'])
app.config['CSW_URL'] = 'http://localhost:8000/csw'

# extensions
db = SQLAlchemy(app)
auth = HTTPBasicAuth()
ma = Marshmallow(app)
CORS(app)

# Functions

# Mengambil data dari Geoserver REST (output JSON)
def georest_get(rest_url, user, password):
    url_get = urllib2.Request(rest_url)
    base64string = base64.encodestring('%s:%s' % (user, password)).replace('\n','')
    url_get.add_header('Content-Type', 'application/json')
    url_get.add_header("Authorization", "Basic %s" % base64string)
    try:
        rest_response = urllib2.urlopen(url_get)
    except urllib2.HTTPError, e:
        if e.code == 401:
            output = '401'
        elif e.code == 404:
            output = '404'
        elif e.code == 503:
            output = '503'
        else:
            output = '999'
    else:
        output = json.loads(rest_response.read())
    return output

def pycsw_get(csw_url, request_param):
    csw_url = csw_url + request_param
    url_get = urllib2.Request(csw_url)
    try:
        pycsw_response = urllib2.urlopen(url_get)
    except urllib2.HTTPError, e:
        if e.code == 401:
            output = '401'
        elif e.code == 404:
            output = '404'
        elif e.code == 503:
            output = '503'
        else:
            output = '999'
    else:
        output = json.loads(pycsw_response.read())
    return output       

# Fungsi pembatasan ekstensi file yang boleh di unggah    
def allowed_file(filename):
    return '.' in filename and filename.rsplit('.',1)[1] in app.config['ALLOWED_EXTENSIONS']

def allowed_vector(filename):
    return '.' in filename and filename.rsplit('.',1)[1] in app.config['ALLOWED_VECTOR']

def allowed_raster(filename):
    return '.' in filename and filename.rsplit('.',1)[1] in app.config['ALLOWED_RASTER']    

def allowed_sld(filename):
    return '.' in filename and filename.rsplit('.',)[1] in set(['sld', 'SLD'])

def allowed_xml(filename):
    return '.' in filename and filename.rsplit('.',)[1] in set(['xml', 'XML'])

def wkt2epsg(wkt, epsg='epsg.txt', forceProj4=False):
    code = None
    p_in = osr.SpatialReference()
    s = p_in.ImportFromWkt(wkt)
    if s == 5:  # invalid WKT
        return None
    if p_in.IsLocal() == 1:  # this is a local definition
        return p_in.ExportToWkt()
    if p_in.IsGeographic() == 1:  # this is a geographic srs
        cstype = 'GEOGCS'
    else:  # this is a projected srs
        cstype = 'PROJCS'
    an = p_in.GetAuthorityName(cstype)
    ac = p_in.GetAuthorityCode(cstype)
    if an is not None and ac is not None:  # return the EPSG code
        return '%s:%s' % \
            (p_in.GetAuthorityName(cstype), p_in.GetAuthorityCode(cstype))
    else:  # try brute force approach by grokking proj epsg definition file
        p_out = p_in.ExportToProj4()
        if p_out:
            if forceProj4 is True:
                return p_out
            f = open(epsg)
            for line in f:
                if line.find(p_out) != -1:
                    m = re.search('<(\\d+)>', line)
                    if m:
                        code = m.group(1)
                        break
            if code:  # match
                return 'EPSG:%s' % code
            else:  # no match
                return None
        else:
            return None

def unzip(source_filename, dest_dir):
    with zipfile.ZipFile(app.config['UPLOAD_FOLDER'] + source_filename) as zf:
        print app.config['UPLOAD_FOLDER'] + source_filename
        for member in zf.infolist():
            # Path traversal defense copied from
            # http://hg.python.org/cpython/file/tip/Lib/http/server.py#l789
            words = member.filename.split('/')
            path = app.config['UPLOAD_FOLDER'] + dest_dir.split('.')[0]   
            print "Path : " + path  
            if not os.path.exists(path):
                os.makedirs(path)
            for word in words[:-1]:
                while True:
                    drive, word = os.path.splitdrive(word)
                    head, word = os.path.split(word)
                    if not drive:
                        break
                if word in (os.curdir, os.pardir, ''):
                    continue
                path = os.path.join(path, word)
            print "Path2 : " + path
            zf.extract(member, path)

def populateORDB(source_shp, database):
    drive = org.GetDriverByName('ESRI Shapesfile')
    shape = app.config['UPLOAD_FOLDER'] + source_shp.split('.')[0] +'/'+ source_shp.split('.')[0]+'.shp'
    # engine = create_engine(app.config['SQLALCHEMY_BIND']['dbdev']) 
    pass

def pgis2pgis(source_db, source_schema, source_table, dest_db, dest_schema, dest_table, identifier):
    pg_conn_input =  "PG:host='" + app.config['DATASTORE_HOST'] + "' port='" + app.config['DATASTORE_PORT'] + "' user='" + app.config['DATASTORE_USER'] + "' dbname='" + source_db + "' password='" + app.config['DATASTORE_PASS'] + "'" 
    pg_conn_output =  "PG:host='" + app.config['DATASTORE_HOST'] + "' port='" + app.config['DATASTORE_PORT'] + "' user='" + app.config['DATASTORE_USER'] + "' dbname='" + dest_db + "' password='" + app.config['DATASTORE_PASS'] + "'" 
    fitur_in = source_schema + '.' + source_table
    fitur_out = dest_schema + '.' + dest_table
    schemaout = "SCHEMA='" + dest_schema + "'"
    sql = "SELECT * from " + fitur_in + " WHERE metadata=" + "'" + identifier + "'"
    print "In/Out:", fitur_in, fitur_out
    print "Conn In/Out:", pg_conn_input, pg_conn_output
    print "SQL:", sql
    try:
        # ogr2ogr.main(["-append", "-a_srs", "EPSG:4326", "-f", "PostgreSQL", "--config", "PG_USE_COPY YES", pg_conn_input, pg_conn_output, fitur_in, fitur_out])
        ogr2ogr.main(["", "-f", "PostgreSQL", "-append", "-nln", fitur_out, "-lco", schemaout, pg_conn_output, pg_conn_input, "-sql", sql])
        msg = "Copy Normal!"
    except:
        msg = "Copy gagal!"
    return msg

def populateDB(source_shp, database):
    # Get Layer EPSG
    print 'Source: ' + source_shp
    driver = ogr.GetDriverByName('ESRI Shapefile')
    shape = app.config['UPLOAD_FOLDER'] + source_shp.split('.')[0] +'/'+ source_shp.split('.')[0]+'.shp'
    pg_conn = "PG:host=" + app.config['DATASTORE_HOST'] + " port=" + app.config['DATASTORE_PORT'] + " user=" + app.config['DATASTORE_USER'] + " dbname=" + database + " password=" + app.config['DATASTORE_PASS']
    print 'Shape: ' + shape
    # print 'PG: ' + pg_conn
    shape_file = driver.Open(shape)
    # uuided = uuid.uuid4()
    dt = datetime.datetime.now()
    print "DT", dt
    uuided = re.sub('[-T:. ]','',str(dt).strip())
    shape_id = source_shp.split('.')[0]+'-'+ str(uuided)
    layer = shape_file.GetLayer()
    crs = layer.GetSpatialRef()
    tipe = 'VECTOR'
    try:
        EPSG = wkt2epsg(crs.ExportToWkt())
        print EPSG
        ogr2ogr.main(["","-f", "PostgreSQL", pg_conn, shape,"-nln", shape_id,"-nlt","PROMOTE_TO_MULTI", "-a_srs",EPSG])
        msg = " ETL Normal!"
        return msg, EPSG, source_shp.split('.')[0], str(uuided), tipe
    except:
        msg = " No Projection defined! Defaulting to EPSG:4326"
        EPSG = "EPSG:4326"
        return msg, EPSG, source_shp.split('.')[0], str(uuided), tipe
        ogr2ogr.main(["","-f", "PostgreSQL", pg_conn, shape,"-nln", shape_id,"-nlt","PROMOTE_TO_MULTI", "-a_srs",EPSG])
    # driver.Close(shape)
    # ogr2ogr.main(["","-f", "PostgreSQL", pg_conn, shape,"-nlt","PROMOTE_TO_MULTI"])

def populateKUGI(source_shp, database, schema, table, scale):
    # Get Layer EPSG
    print 'Source: ' + source_shp
    driver = ogr.GetDriverByName('ESRI Shapefile')
    shape = app.config['UPLOAD_FOLDER'] + source_shp.split('.')[0] +'/'+ source_shp.split('.')[0]+'.shp'
    pg_conn = "PG:host=" + app.config['DATASTORE_HOST'] + " port=" + app.config['DATASTORE_PORT'] + " user=" + app.config['DATASTORE_USER'] + " dbname=" + database + " password=" + app.config['DATASTORE_PASS']
    print 'Shape: ' + shape
    # print 'PG: ' + pg_conn
    shape_file = driver.Open(shape)
    uuided = uuid.uuid4()
    shape_id = source_shp.split('.')[0]+'-'+ str(uuided)
    layer = shape_file.GetLayer()
    crs = layer.GetSpatialRef()
    tipe = 'VECTOR'
    fitur = schema + '.' + table + '_' + scale
    print fitur
    try:
        EPSG = wkt2epsg(crs.ExportToWkt())
        print EPSG
        try:
            ogro = ogr2ogr.main(["", "-append","-f", "PostgreSQL", pg_conn, shape,"-nln", fitur,"-nlt","PROMOTE_TO_MULTI", "-a_srs", EPSG])
            if ogro:
                msg = " ETL Normal!"
            else:
                msg = " Terjadi kegagalan import!"
        except:
            msg = " Terjadi kegagalan import!"
        return msg, EPSG, source_shp.split('.')[0], str(uuided), tipe, ogro
    except:
        msg = " No Projection defined! Defaulting to EPSG:4326"
        EPSG = "EPSG:4326"
        return msg, EPSG, source_shp.split('.')[0], str(uuided), tipe
        try:
            ogro = ogr2ogr.main(["", "-append","-f", "PostgreSQL", pg_conn, shape,"-nln", fitur,"-nlt","PROMOTE_TO_MULTI", "-a_srs", EPSG])
            if ogro:
                msg = " ETL Normal!"
            else:
                msg = " Terjadi kegagalan import!"
        except:
            msg = " Terjadi kegagalan import!"
        return msg, EPSG, source_shp.split('.')[0], str(uuided), tipe, ogro

def populateRS(source_ras):
    print source_ras
    catalog = Catalog(app.config['GEOSERVER_REST_URL'], app.config['GEOSERVER_USER'], app.config['GEOSERVER_PASS'])
    name = source_ras.split('.')[0]
    uuided = uuid.uuid4()
    layer_id = name + '-' + str(uuided)
    layer_file = app.config['RASTER_FOLDER']+layer_id.replace('-','_')+'.tif'
    print layer_file
    copyfile(app.config['UPLOAD_FOLDER']+source_ras+'/'+source_ras+'.tif', layer_file)
    datafile = gdal.Open(layer_file)
    EPSG = wkt2epsg(datafile.GetProjection())
    tipe = 'RASTER'
    msg = " Raster projection: " + EPSG
    print 'Source: ' + source_ras
    return msg, EPSG, layer_id, str(uuided),tipe

def refresh_dbmetafieldview(database):
    # engine = create_engine(app.config['SQLALCHEMY_BINDS'][database])
    if database == 'dbdev':
        db = 'palapa_dev'
    if database == 'dbprod':
        db = 'palapa_prod'
    if database == 'dbpub':
        db = 'palapa_pub'
    con = psycopg2.connect(dbname=db, user=app.config['DATASTORE_USER'], host=app.config['DATASTORE_HOST'], password=app.config['DATASTORE_PASS'])
    con.set_isolation_level(ISOLATION_LEVEL_AUTOCOMMIT)
    cur = con.cursor()
    sql = "SELECT public._a_cekmetadata()"
    cur.execute(sql)
    msg = "Refreshed" 
    # print "DB:", database
    # try:
    #     result = engine.execute(func._a_cekmetadata())
    #     for row in result:
    #         print "RESULT:", row
    #     db.session.commit()
    #     msg = "Refreshed" 
    # except:
    #     msg = "Terjadi kesalahan!"  
    # print msg
    return msg

def get_all(myjson, key):
    if type(myjson) == str:
        myjson = json.loads(myjson)
    if type(myjson) is dict:
        for jsonkey in myjson:
            if type(myjson[jsonkey]) in (list, dict):
                get_all(myjson[jsonkey], key)
            elif jsonkey == key:
                print myjson[jsonkey]
    elif type(myjson) is list:
        for item in myjson:
            if type(item) in (list, dict):
                get_all(item, key)
           

# Database
class User(db.Model):
    __tablename__ = 'users'
    #id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(128), index=True, primary_key=True)
    password = db.Column(db.String(254))
    enabled = db.Column(db.String(1))
    kelas = db.Column(db.String(64))
    individualname = db.Column(db.String(128))

    def hash_password(self, password):
        # self.password_hash = pwd_context.encrypt(password)
        self.password = 'plain:' + password

    def verify_password(self, password):
        password_hash = pwd_context.encrypt(self.password.split(':')[1])
        return pwd_context.verify(password, password_hash)

    # perhatikan token duration
    def generate_auth_token(self, expiration=60):
        # s = Serializer(app.config['SECRET_KEY'], expires_in=expiration)
        s = jwt.encode({'username': self.name, 'exp': datetime.datetime.utcnow() + datetime.timedelta(seconds=30)}, app.config['SECRET_KEY'], algorithm='HS256')
        return s

    @staticmethod
    def verify_auth_token(token):
        print "token: ", token
        # s = Serializer(app.config['SECRET_KEY'])
        # s = jwt.decode(token, app.config['SECRET_KEY'], algorithms=['HS256'])
        s = jwt.encode({'username': token, 'exp': datetime.datetime.utcnow() + datetime.timedelta(seconds=30)}, app.config['SECRET_KEY'], algorithm='HS256')
        try:
            data = jwt.decode(s,app.config['SECRET_KEY'], algorithms=['HS256'])
            print data
            # data = s.loads(token)
        except SignatureExpired:
            return None    # valid token, but expired
        except BadSignature:
            return None    # invalid token
        user = User.query.get(data['username'])
        return user

class UserSchema(ma.ModelSchema):
    class Meta:
        model = User

# class MetaList(db.Model):
#     __tablename__ = 't_metadata'

class Userwgroup(db.Model):
    __tablename__ = 'v_users'
    name = db.Column(db.String(128), index=True, primary_key=True)
    groupname = db.Column(db.String(128))
    rolename = db.Column(db.String(64))
    enabled = db.Column(db.String(1))
    individualname = db.Column(db.String(128))

class UserwgroupSchema(ma.ModelSchema):
    class Meta:
        model = Userwgroup 

class Group(db.Model):
    __tablename__ = 'groups'
    name = db.Column(db.String(128), index=True, primary_key=True)
    enabled = db.Column(db.String(1))
    organization = db.Column(db.String(128))
    url = db.Column(db.String(256))
    phone = db.Column(db.String(32))
    fax = db.Column(db.String(32))
    address = db.Column(db.Text)
    city = db.Column(db.String(64))
    administrativearea = db.Column(db.String(64))
    postalcode = db.Column(db.String(8))
    email = db.Column(db.String(128))
    country = db.Column(db.String(128))

class GroupSchema(ma.ModelSchema):
    class Meta:
        model = Group

class Group_Members(db.Model):
    __tablename__ = 'group_members'
    groupname = db.Column(db.String(128), primary_key=True)
    username = db.Column(db.String(128), primary_key=True)

class Group_MembersSchema(ma.ModelSchema):
    class Meta:
        model = Group_Members    

class Roles(db.Model):
    __tablename__ = 'roles'
    name = db.Column(db.String(64), primary_key=True)
    parent = db.Column(db.String(64))

class RolesSchema(ma.ModelSchema):
    class Meta:
        model = Roles

class Group_Roles(db.Model):
    __tablename__ = 'group_roles'
    groupname = db.Column(db.String(128), primary_key=True)
    rolename = db.Column(db.String(64), primary_key=True)

class Group_RolesSchema(ma.ModelSchema):
    class Meta:
        model = Group_Roles

class User_Roles(db.Model):
    __tablename__ = 'user_roles'
    username = db.Column(db.String(128), primary_key=True)
    rolename = db.Column(db.String(64), primary_key=True)

class User_RolesSchema(ma.ModelSchema):
    class Meta:
        model = User_Roles        

class User_Props(db.Model):
    __tablename__ = 'user_props'
    username = db.Column(db.String(128), primary_key=True)
    propname = db.Column(db.String(64), primary_key=True)
    provalue = db.Column(db.String(2048))

class UserAuth(object):
    def __init__(self, username, password, kelas):
        self.username = username
        self.password = password
        self.kelas = kelas
    def __str__(self):
        return self.username
        # return "User(user='%s')" % self.username

class Metalinks(db.Model):
    __tablename__ = 'metalinks'
    identifier = db.Column(db.String(128), primary_key=True)
    workspace = db.Column(db.String(128))
    metatick =  db.Column(db.String(1))
    akses = db.Column(db.String(32))
    published = db.Column(db.String(1))
    xml = db.Column(db.Text)

class MetalinksSchema(ma.ModelSchema):
    class Meta:
        model = Metalinks        

class Metakugi(db.Model):
    __tablename__ = 'metakugi'
    identifier = db.Column(db.String(128), primary_key=True)
    skema = db.Column(db.String(128))
    fitur = db.Column(db.String(128))
    workspace = db.Column(db.String(128))
    metatick =  db.Column(db.String(1))
    akses = db.Column(db.String(32))
    published = db.Column(db.String(1))
    xml = db.Column(db.Text)
    tipe = db.Column(db.String(16))

class MetakugiSchema(ma.ModelSchema):
    class Meta:
        model = Metakugi            

class Sistem(db.Model):
    __tablename__ = 'sistem'
    key = db.Column(db.String(128), primary_key=True)
    value = db.Column(db.Text)

class SistemSchema(ma.ModelSchema):
    class Meta:
        model = Sistem        

def identity(payload):
    print 'Identity:', user
    return user

@auth.verify_password
def verify_password(username_or_token, password):
    # first try to authenticate by token
    user = User.verify_auth_token(username_or_token)
    print "User: ", user
    if not user:
        # try to authenticate with username/password
        user = User.query.filter_by(name=username_or_token).first()
        if not user or not user.verify_password(password):
            return False
    user_auth = UserAuth(username_or_token, password, user.kelas)        
    g.user = user
    print 'User auth:', user_auth
    return user_auth

pjwt = JWT(app, verify_password, identity)    

# @auth.verify_password
# def verify_password(username_or_token, password):
#     # first try to authenticate by token
#     user = User.verify_auth_token(username_or_token)
#     if not user:
#         # try to authenticate with username/password
#         user = User.query.filter_by(name=username_or_token).first()
#         if not user or not user.verify_password(password):
#             return False
#     g.user = user
#     return True    

@app.after_request
def after_request(response):
    response.headers.add('Access-Control-Allow-Origin', '*')
    if request.method == 'OPTIONS':
        response.headers['Access-Control-Allow-Methods'] = 'DELETE, GET, POST, PUT'
        headers = request.headers.get('Access-Control-Request-Headers')
        if headers:
            response.headers['Access-Control-Allow-Headers'] = headers
    return response

# ROUTES ....

@app.route('/api/sisteminfo')
def sisteminfo():
    info = {}
    sisinfo = db.session.query(Sistem).all()
    for row in sisinfo:
        print row.key, row.value
        info[row.key] = row.value
    resp = json.dumps(info)
    print info
    return Response(resp, mimetype='application/json')    

@app.route('/api/sisteminfo/edit', methods=['POST'])
def sisteminfoedit():
    if request.method == 'POST':
        header = json.loads(urllib2.unquote(request.data).split('=')[1])
        organization = urllib2.unquote(header['pubdata']['organization'])
        url = urllib2.unquote(header['pubdata']['url'])
        individualname = urllib2.unquote(header['pubdata']['individualname'])
        positionname = urllib2.unquote(header['pubdata']['positionname'])
        phone = urllib2.unquote(header['pubdata']['phone'])
        fax = urllib2.unquote(header['pubdata']['fax'])
        address = urllib2.unquote(header['pubdata']['address'])
        city = urllib2.unquote(header['pubdata']['city'])
        administrativearea = urllib2.unquote(header['pubdata']['administrativearea'])
        postalcode = urllib2.unquote(header['pubdata']['postalcode'])
        country = urllib2.unquote(header['pubdata']['country'])
        email = urllib2.unquote(header['pubdata']['email'])
        hoursofservice = urllib2.unquote(header['pubdata']['hoursofservice'])
        contactinstruction = urllib2.unquote(header['pubdata']['contactinstruction'])
        print header
        r_address = Sistem.query.filter_by(key='address').first()
        r_administrativearea = Sistem.query.filter_by(key='administrativearea').first()
        r_city = Sistem.query.filter_by(key='city').first()
        r_contactinstruction = Sistem.query.filter_by(key='contactinstruction').first()
        r_country = Sistem.query.filter_by(key='country').first()
        r_email = Sistem.query.filter_by(key='email').first()
        r_fax = Sistem.query.filter_by(key='fax').first()
        r_hoursofservice = Sistem.query.filter_by(key='hoursofservice').first()
        r_individualname = Sistem.query.filter_by(key='individualname').first()
        r_organization = Sistem.query.filter_by(key='organization').first()
        r_phone = Sistem.query.filter_by(key='phone').first()
        r_positionname = Sistem.query.filter_by(key='positionname').first()
        r_postalcode= Sistem.query.filter_by(key='postalcode').first()
        r_url = Sistem.query.filter_by(key='url').first()
        r_address.value = address
        r_administrativearea.value = administrativearea
        r_city.value = city
        r_contactinstruction.value = contactinstruction
        r_country.value = country
        r_email.value = email
        r_fax.value = fax
        r_hoursofservice.value = hoursofservice
        r_individualname.value = individualname
        r_organization.value = organization
        r_phone.value = phone
        r_positionname.value = positionname
        r_postalcode.value = postalcode
        r_url.value = url
        db.session.commit()
        return jsonify({'Result': True, 'MSG':'OK!'})

@app.route('/api/login', methods=['POST', 'OPTIONS'])
def login():
    if request.method == 'OPTIONS':
        return jsonify({'Result': False, 'MSG':'POST Only!'})
    if request.method == 'POST':
        header = json.loads(urllib2.unquote(request.data))
        # print 'User:', header['username'], 'Password:', header['password']
        if User.query.filter_by(name=header['username']).first() is not None:
            user = User.query.filter_by(name=header['username']).first() 
            print user
            # print 'User', user.name, 'Password', user.password
            if user.name == header['username']:   
                if user.password.split(':')[1] == header['password']:
                    group = Group_Members.query.filter_by(username=header['username']).first()
                    print 'Grup:',group
                    if group is not None:
                        return jsonify({'Result': True, 'MSG':'Valid Info', 'user':user.name, 'kelas':user.kelas, 'grup':group.groupname, 'indiviualname':user.individualname})
                    else:
                        return jsonify({'Result': True, 'MSG':'Valid Info', 'user':user.name, 'kelas':user.kelas, 'grup':'', 'indiviualname':user.individualname})
                else:
                    return jsonify({'Result': False, 'MSG':'Password salah!'})
        else:
            return jsonify({'Result': False, 'MSG':'User tidak terdaftar!'})

@app.route('/api/users', methods=['POST'])
# @auth.login_required
def new_user():
    if request.method == 'POST':
        header = json.loads(urllib2.unquote(request.data).split('=')[1])
    print header['pubdata'] 
    name = header['pubdata'] ['name']
    password = header['pubdata'] ['password']
    grup = header['pubdata'] ['grup']
    role = header['pubdata'] ['role']
    kelas = header['pubdata'] ['kelas']
    enabled = header['pubdata'] ['enabled']
    individualname = urllib2.unquote(header['pubdata'] ['individualname'])
    if name is None or password is None:
        abort(400)    # missing arguments
    if User.query.filter_by(name=name).first() is not None:
        abort(400)    # existing user
    user = User(name=name)
    user.hash_password(password)
    user.enabled = enabled
    user.kelas = kelas
    user.individualname = individualname
    user_grup = Group_Members(groupname=grup)
    user_grup.groupname = grup
    user_grup.username = name
    user_role = User_Roles(rolename=role)
    user_role.rolename = role
    user_role.username = name
    db.session.add(user_role)
    db.session.add(user_grup)
    db.session.add(user)
    db.session.commit()
    return (jsonify({'name': user.name}), 201,
            {'Location': url_for('get_user', name=user.name, _external=True)})

@app.route('/api/users/<string:name>')
def get_user(name):
    user = User.query.get(name)
    if not user:
        abort(400)
    return jsonify({'name': user.name})

@app.route('/api/users/list')
# @auth.login_required
def list_user():
    list_user = User.query.filter(User.name != 'admin').with_entities(User.name, User.enabled, User.individualname)
    users = UserSchema(many=True)
    output = users.dump(list_user)
    return json.dumps(output.data)

@app.route('/api/user/delete', methods=['POST'])
# @auth.login_required
def delete_user():
    if request.method == 'POST':
        header = json.loads(urllib2.unquote(request.data).split('=')[1])
    print header['pubdata'] 
    name = header['pubdata']['name'] 
    if name is None:
        abort(400)
    if User.query.filter_by(name=name).first() is None:
        abort(400)
    if Group_Members.query.filter_by(username=name):
        Group_Members.query.filter_by(username=name).delete()
    if User_Roles.query.filter_by(username=name):
        User_Roles.query.filter_by(username=name).delete()
    user = User(name=name)
    User.query.filter_by(name=name).delete()
    db.session.commit()
    return jsonify({'deleted': user.name})           

@app.route('/api/userswgroup/list')
# @auth.login_required
def list_userswgroup():
    list_userswgroup = Userwgroup.query.filter(Userwgroup.name != 'admin').with_entities(Userwgroup.name, Userwgroup.groupname, Userwgroup.rolename, Userwgroup.enabled, Userwgroup.individualname)
    users = UserwgroupSchema(many=True)
    output = users.dump(list_userswgroup)
    return json.dumps(output.data)    

@app.route('/api/groups', methods=['POST'])
# @auth.login_required
def new_groups():
    if request.method == 'POST':
        header = json.loads(urllib2.unquote(request.data).split('=')[1])
    print header['pubdata'] 
    name = header['pubdata']['name'] 
    organization = urllib2.unquote(header['pubdata']['organization'])
    url = header['pubdata']['url'] 
    phone = header['pubdata']['phone'] 
    fax = header['pubdata']['fax'] 
    address = urllib2.unquote(header['pubdata']['address'])
    city = urllib2.unquote(header['pubdata']['city'])
    administrativearea = urllib2.unquote(header['pubdata']['administrativearea'])
    postalcode = header['pubdata']['postalcode'] 
    email = header['pubdata']['email'] 
    country = "Indonesia"
    print 'Grup Baru:', name
    if name is None:
        print 'No Group name'
        abort(400)
    if Group.query.filter_by(name=name).first() is not None:
        print 'Grup sudah ada'
        abort(400)
    if Roles.query.filter_by(name=name).first() is not None:
        print 'Role sudah ada'
        abort(400)    
    group = Group(name=name,organization=organization,url=url,phone=phone,fax=fax,address=address,city=city,administrativearea=administrativearea,postalcode=postalcode,email=email,country=country)
    role = Roles(name=name)
    group.enabled =  header['pubdata']['enabled'] 
    db.session.add(group)
    db.session.add(role)
    db.session.commit()
    print 'Commited'
    catalog = Catalog(app.config['GEOSERVER_REST_URL'], app.config['GEOSERVER_USER'], app.config['GEOSERVER_PASS'])
    new_workspace = catalog.create_workspace(name,name)
    # Create database
    # sqlalchemy_utils.create_database(app.config['SQLALCHEMY_DATASTORE'] + name, encoding='utf8', template='template_postgis_wraster')
    # engine = create_engine(app.config['SQLALCHEMY_DATABASE_URI'])
    #engine.set_isolation_level(ISOLATION_LEVEL_AUTOCOMMIT)
    #sql ="CREATE DATABASE %s ENCODING 'UTF-8' TEMPLATE template_postgis_wraster owner %s;" % (str(name), str(app.config['DATASTORE_USER']))
    #create_db = engine.execute(sql)
    con = psycopg2.connect(dbname=app.config['DATASTORE_DB'], user=app.config['DATASTORE_USER'], host=app.config['DATASTORE_HOST'], password=app.config['DATASTORE_PASS'])
    con.set_isolation_level(ISOLATION_LEVEL_AUTOCOMMIT)
    cur = con.cursor()
    sql ="CREATE DATABASE \"%s\" ENCODING 'UTF-8' TEMPLATE template_postgis_wraster owner \"%s\";" % (str(name), str(app.config['DATASTORE_USER']))
    cur.execute(sql)
    print sql
    # Create Store
    new_store = catalog.create_datastore(name,name)
    new_store.connection_parameters.update(host=app.config['DATASTORE_HOST'], port=app.config['DATASTORE_PORT'], database=name,user=app.config['DATASTORE_USER'], passwd=app.config['DATASTORE_PASS'], dbtype='postgis', schema='public')
    # layers security
    with open(app.config['GEOSERVER_LAYERS_PROP'], 'a') as file:
        file.write(name + '.*.a=' + name + '\n')
    catalog.save(new_store)
    catalog.reload()
        # return jsonify({'RTN': 'Workspace ' + workspace + ' dibuat.'})
    return (jsonify({'group': group.name}), 201,
            {'Location': url_for('get_group', name=group.name, _external=True)})

@app.route('/api/group/edit', methods=['POST'])
def groupedit():
    if request.method == 'POST':
        header = json.loads(urllib2.unquote(request.data).split('=')[1])
    print header['pubdata']     
    name = header['pubdata']['name'] 
    organization = urllib2.unquote(header['pubdata']['organization'])
    url = header['pubdata']['url'] 
    phone = header['pubdata']['phone'] 
    fax = header['pubdata']['fax'] 
    address = urllib2.unquote(header['pubdata']['address'])
    city = urllib2.unquote(header['pubdata']['city'])
    administrativearea = urllib2.unquote(header['pubdata']['administrativearea'])
    postalcode = header['pubdata']['postalcode'] 
    email = header['pubdata']['email'] 
    country = "Indonesia"
    selected_group = Group.query.filter_by(name=name).first()
    selected_group.organization = organization
    selected_group.url = url
    selected_group.phone = phone
    selected_group.fax = fax
    selected_group.address = address
    selected_group.city = city
    selected_group.administrativearea = administrativearea
    selected_group.postalcode = postalcode
    selected_group.email = email
    selected_group.country = country
    db.session.commit()
    return jsonify({'edited': name})

@app.route('/api/preparekugi', methods=['POST'])
# @auth.login_required
def kugiprepare():
    if request.method == 'POST':
        header = json.loads(urllib2.unquote(request.data).split('=')[1])
    print header['pubdata'] 
    name = header['pubdata']['name'] 
    print 'Grup Baru:', name
    if name is None:
        print 'No Group name'
        abort(400)
    if Group.query.filter_by(name=name).first() is not None:
        print 'Grup sudah ada'
        abort(400)
    if Roles.query.filter_by(name=name).first() is not None:
        print 'Role sudah ada'
        abort(400)    
    group = Group(name=name)
    role = Roles(name=name)
    group.enabled = 'Y'
    db.session.add(group)
    db.session.add(role)
    db.session.commit()
    print 'Commited'
    catalog = Catalog(app.config['GEOSERVER_REST_URL'], app.config['GEOSERVER_USER'], app.config['GEOSERVER_PASS'])
    new_workspace = catalog.create_workspace(name,name)
    # con = psycopg2.connect(dbname=app.config['DATASTORE_DB'], user=app.config['DATASTORE_USER'], host=app.config['DATASTORE_HOST'], password=app.config['DATASTORE_PASS'])
    # con.set_isolation_level(ISOLATION_LEVEL_AUTOCOMMIT)
    # cur = con.cursor()
    # sql ="CREATE DATABASE \"%s\" ENCODING 'UTF-8' TEMPLATE template_postgis_wraster owner \"%s\";" % (str(name), str(app.config['DATASTORE_USER']))
    # cur.execute(sql)
    # print sql
    # Create Store
    new_store = catalog.create_datastore(name,name)
    new_store.connection_parameters.update(host=app.config['DATASTORE_HOST'], port=app.config['DATASTORE_PORT'], database='palapa_pub',user=app.config['DATASTORE_USER'], passwd=app.config['DATASTORE_PASS'], dbtype='postgis', schema='public')
    # layers security
    with open(app.config['GEOSERVER_LAYERS_PROP'], 'a') as file:
        file.write(name + '.*.a=' + name + '\n')
    catalog.save(new_store)
    catalog.reload()
        # return jsonify({'RTN': 'Workspace ' + workspace + ' dibuat.'})
    return (jsonify({'group': group.name}), 201,
            {'Location': url_for('get_group', name=group.name, _external=True)})

@app.route('/api/group/list')
# @auth.login_required
def list_group():
    list_group = User.query.with_entities(Group.name, Group.enabled, Group.organization, Group.url, Group.phone, Group.fax, Group.address, Group.city, Group.administrativearea, Group.postalcode, Group.email, Group.country)
    groups = GroupSchema(many=True)
    output = groups.dump(list_group)
    return json.dumps(output.data)        

@app.route('/api/role/list')
# @auth.login_required
def list_role():
    list_role = User.query.with_entities(Roles.name, Roles.parent)
    roles = RolesSchema(many=True)
    output = roles.dump(list_role)
    return json.dumps(output.data)        

@app.route('/api/group/delete', methods=['POST'])
# @auth.login_required
def delete_groups():
    if request.method == 'POST':
        header = json.loads(urllib2.unquote(request.data).split('=')[1])
    print header['pubdata'] 
    name = header['pubdata']['name'] 
    if name is None:
        abort(400)
    if Group.query.filter_by(name=name).first() is None:
        abort(400)
    group = Group(name=name)
    copyfile(app.config['GEOSERVER_LAYERS_PROP'], app.config['GEOSERVER_LAYERS_PROP'] + '.bak')
    with open(app.config['GEOSERVER_LAYERS_PROP'] + '.bak') as oldfile, open(app.config['GEOSERVER_LAYERS_PROP'], 'w') as newfile:
        for line in oldfile:
            if not name in line:
                newfile.write(line)
    Group.query.filter_by(name=name).delete()
    db.session.commit()
    return jsonify({'deleted': group.name})           

@app.route('/api/groups/<string:name>')
def get_group(name):
    group = Group.query.get(name)
    if not group:
        abort(400)
    return jsonify({'name': group.name})            

@app.route('/api/token')
@auth.login_required
def get_auth_token():
    token = g.user.generate_auth_token(60)
    return jsonify({'token': token.decode('ascii'), 'duration': 60})

@app.route('/api/resource')
@jwt_required()
def get_resource():
    return jsonify({'data': 'Hello, %s!' % g.user.name})

# GeoServer REST fetch

@app.route('/api/getWMSlayers')
def get_wmslayers():
    layers = []
    workspaces = georest_get(app.config['GEOSERVER_REST_URL'] + 'workspaces.json', app.config['GEOSERVER_USER'], app.config['GEOSERVER_PASS'])
    workspaces_items = workspaces['workspaces']['workspace']
    for i, ival in enumerate(workspaces_items):
        workspaces_item = georest_get(ival['href'] , app.config['GEOSERVER_USER'], app.config['GEOSERVER_PASS'])
        datastores = workspaces_item['workspace']['dataStores']
        coveragestores = workspaces_item['workspace']['coverageStores']
        datastores_items = georest_get(datastores, app.config['GEOSERVER_USER'], app.config['GEOSERVER_PASS'])
        coveragestores_items = georest_get(coveragestores, app.config['GEOSERVER_USER'], app.config['GEOSERVER_PASS'])
        try:
            for j, val in enumerate(datastores_items['dataStores']['dataStore']):
                datastore = val['href']
                store = georest_get(val['href'] , app.config['GEOSERVER_USER'], app.config['GEOSERVER_PASS'])
                features = georest_get(store['dataStore']['featureTypes'] , app.config['GEOSERVER_USER'], app.config['GEOSERVER_PASS'])
                for k, val in enumerate(features['featureTypes']['featureType']):
                    layer = {}
                    feature = georest_get(val['href'], app.config['GEOSERVER_USER'], app.config['GEOSERVER_PASS'])
                    print k, feature['featureType']['name']
                    layer["layer_id"] = feature['featureType']['name']
                    layer["layer_name"] = feature['featureType']['title']
                    layer["layer_abstract"] = feature['featureType']['abstract']
                    layer["layer_aktif"] = feature['featureType']['enabled']
                    layer["layer_srs"] = feature['featureType']['srs']
                    layer["layer_minx"] = feature['featureType']['latLonBoundingBox']['minx']
                    layer["layer_maxx"] = feature['featureType']['latLonBoundingBox']['maxx']
                    layer["layer_miny"] = feature['featureType']['latLonBoundingBox']['miny']
                    layer["layer_maxy"] = feature['featureType']['latLonBoundingBox']['maxy']
                    resource_url = app.config['GEOSERVER_REST_URL'] + 'layers/' + feature['featureType']['name'] + '.json'
                    resource = georest_get(resource_url, app.config['GEOSERVER_USER'], app.config['GEOSERVER_PASS'])
                    layer["layer_style"] = resource['layer']['defaultStyle']['name']
                    layer["layer_type"] = resource['layer']['type']
                    layer["layer_nativename"] = feature['featureType']['namespace']['name'] + ':' + feature['featureType']['name']
                    layer["workspace"] = feature['featureType']['namespace']['name']
                    layers.append(layer)
        except:
            pass
        try:
            for o, val in enumerate(coveragestores_items['coverageStores']['coverageStore']):
                layer = {}
                coveragestore = val['href']
                try:
                    coverage = georest_get(val['href'] , app.config['GEOSERVER_USER'], app.config['GEOSERVER_PASS'])
                    rasters = georest_get(coverage['coverageStore']['coverages'] , app.config['GEOSERVER_USER'], app.config['GEOSERVER_PASS'])
                    raster = georest_get(rasters['coverages']['coverage'][0]['href'], app.config['GEOSERVER_USER'], app.config['GEOSERVER_PASS'])
                    print o, raster['coverage']['name']
                    layer["layer_id"] = raster['coverage']['name']
                    layer["layer_name"] = raster['coverage']['title']
                    layer["layer_abstract"] = raster['coverage']['abstract']
                    layer["layer_aktif"] = raster['coverage']['enabled']
                    layer["layer_srs"] = raster['coverage']['srs']
                    layer["layer_minx"] = raster['coverage']['latLonBoundingBox']['minx']
                    layer["layer_maxx"] = raster['coverage']['latLonBoundingBox']['maxx']
                    layer["layer_miny"] = raster['coverage']['latLonBoundingBox']['miny']
                    layer["layer_maxy"] = raster['coverage']['latLonBoundingBox']['maxy']
                    resource_url = app.config['GEOSERVER_REST_URL'] + 'layers/' + raster['coverage']['name'] + '.json'
                    resource = georest_get(resource_url, app.config['GEOSERVER_USER'], app.config['GEOSERVER_PASS'])
                    layer["layer_style"] = resource['layer']['defaultStyle']['name']
                    layer["layer_type"] = resource['layer']['type']       
                    layer["layer_nativename"] =  raster['coverage']['namespace']['name'] + ':' + raster['coverage']['name']    
                    layers.append(layer)
                except:
                    pass
        except:
            pass
        resp = json.dumps(layers) 
    return Response(resp, mimetype='application/json')

@app.route('/api/getstyles')
# @auth.login_required
def get_styles():
    styles = georest_get(app.config['GEOSERVER_REST_URL'] + 'styles.json', app.config['GEOSERVER_USER'], app.config['GEOSERVER_PASS'])
    return json.dumps(styles['styles']['style'])   

# GeoServer REST POST

@app.route('/api/styles/add', methods=['POST'])
# @auth.login_required
def add_style():
    if request.method == 'POST':
        # check if the post request has the file part
        if 'file' not in request.files:
            print 'No file part' 
            resp = json.dumps({'MSG': 'No file part'})
            return Response(resp, mimetype='application/json')
        file = request.files['file']
        print file
        # if user does not select file, browser also
        # submit a empty part without filename
        if file.filename == '':
            print 'No selected file' 
            resp = json.dumps({'RTN': 'ERR', 'MSG': 'No selected file'})
            return Response(resp, status=405, mimetype='application/json')
        if not allowed_sld(file.filename):
            resp = json.dumps({'RTN': 'ERR', 'MSG': 'Type not allowed'})
            return Response(resp, status=405, mimetype='application/json')
        if file and allowed_sld(file.filename):
            filename = secure_filename(file.filename)
            file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
            print "Filename: " + filename.split('.')[0]
            sldfile = app.config['UPLOAD_FOLDER'] + filename.split('.')[0] + '.sld'
            print "Shapefile: " + sldfile
            if os.path.exists(sldfile):
                print "File SLD OK"
                catalog = Catalog(app.config['GEOSERVER_REST_URL'], app.config['GEOSERVER_USER'], app.config['GEOSERVER_PASS'])
                sld = open(os.path.join(app.config['UPLOAD_FOLDER'], filename))
                try:
                    catalog.create_style(filename.split('.')[0], sld.read()) 
                    resp = json.dumps({'RTN': filename, 'MSG': 'Upload Success!'})
                except:
                    resp = json.dumps({'RTN': filename, 'MSG': 'Error, Style dengan nama yang sama sudah ada!'})
                return Response(resp, mimetype='application/json')
            else:
                resp = json.dumps({'RTN': 'ERR', 'MSG': 'No SHAPE file!'})
                return Response(resp, status=405, mimetype='application/json')
        resp = json.dumps({'RTN': 'ERR', 'MSG': 'ERROR'})
        return Response(resp, mimetype='application/json')    
    return jsonify({'RTN': 'Hello!'})

@app.route('/api/styles/modify')
# @auth.login_required
def modify_style():
    return jsonify({'RTN': 'Hello!'})

@app.route('/api/styles/delete', methods=['POST'])
# @auth.login_required
def delete_style():
    if request.method == 'POST':
        header = json.loads(urllib2.unquote(request.data).split('=')[1])
        print header['pubdata'] 
        catalog = Catalog(app.config['GEOSERVER_REST_URL'], app.config['GEOSERVER_USER'], app.config['GEOSERVER_PASS'])
        style = catalog.get_style(header['pubdata'])
        catalog.delete(style)
        catalog.reload()
        return jsonify({'RTN': 'Deleted!'})

@app.route('/api/layers/info/<string:layers>')
# @auth.login_required
def layer_info(layers):
    decoded_url = app.config['GEOSERVER_REST_URL'] + 'layers/' + layers + '.json'
    print decoded_url
    resource_info = {}
    resource = georest_get(decoded_url, app.config['GEOSERVER_USER'], app.config['GEOSERVER_PASS'])
    resource_info['name']=resource['layer']['name']
    resource_info['defaultstyle']=resource['layer']['defaultStyle']['name']
    resource_info['type']=resource['layer']['type']
    return jsonify(resource_info)

@app.route('/api/layers/add')
# @auth.login_required
def add_layer():
    return jsonify({'RTN': 'Hello!'})

@app.route('/api/layers/modify', methods=['POST'])
# @auth.login_required
def modify_layer():
    if request.method == 'POST':
        header = json.loads(urllib2.unquote(request.data).split('=')[1])
        print header['pubdata']
        catalog = Catalog(app.config['GEOSERVER_REST_URL'], app.config['GEOSERVER_USER'], app.config['GEOSERVER_PASS'])
        resource = catalog.get_resource(header['pubdata']['id'])
        resource.title = urllib2.unquote(header['pubdata']['title'])
        resource.abstract = urllib2.unquote(header['pubdata']['abstract'])
        resource.enabled = header['pubdata']['aktif']
        catalog.save(resource)
        catalog.reload()
        if header['pubdata']['tipe'] == 'VECTOR':
            layer = catalog.get_layer(header['pubdata']['nativename'])
            layer._set_default_style(header['pubdata']['style'])
            msg = 'Set vector style'
            print header['pubdata']['nativename'], header['pubdata']['style']
        if header['pubdata']['tipe'] == 'RASTER':
            layer = catalog.get_layer(header['pubdata']['id'])
            layer._set_default_style(header['pubdata']['style'])
            msg ='Set raster style'
        catalog.save(layer)
        catalog.reload()
    return jsonify({'RTN': msg})

@app.route('/api/layers/delete', methods=['POST'])
# @auth.login_required
def delete_layer():
    if request.method == 'POST':
        header = json.loads(urllib2.unquote(request.data).split('=')[1])
        print header['pubdata'] 
        catalog = Catalog(app.config['GEOSERVER_REST_URL'], app.config['GEOSERVER_USER'], app.config['GEOSERVER_PASS'])
        layer = catalog.get_layer(header['pubdata'])
        del_layer = catalog.delete(layer)
        catalog.reload()
    return jsonify({'RTN': 'Deleted!'})

@app.route('/api/layers/populate/<string:file>', methods=['POST'])
# @auth.login_required
def populate_layer(file):
    if request.method == 'POST':
        return jsonify({'RTN': 'File ' + file + ' dimuat ke database.'})
    return jsonify({'RTN': 'R.I.P'})

@app.route('/api/workspace/add/<string:workspace>', methods=['POST'])
# @auth.login_required
def add_workspace(workspace):
    if request.method == 'POST':
        catalog = Catalog(app.config['GEOSERVER_REST_URL'], app.config['GEOSERVER_USER'], app.config['GEOSERVER_PASS'])
        new_workspace = catalog.create_workspace(workspace,workspace)
        return jsonify({'RTN': 'Workspace ' + workspace + ' dibuat.'})
    return jsonify({'RTN': 'Permintaan salah!'})

@app.route('/api/workspace/modify')
# @auth.login_required
def modify_workspace():
    return jsonify({'RTN': 'Hello!'})

@app.route('/api/workspace/delete')
# @auth.login_required
def delete_workspace():
    return jsonify({'RTN': 'Hello!'})

@app.route('/api/store/add/<string:store>', methods=['POST'])
# @auth.login_required
def add_store(store):
    if request.method == 'POST':
        # Create database
        sqlalchemy_utils.create_database(app.config['SQLALCHEMY_DATASTORE'] + store, encoding='utf8', template='template_postgis')
        # Create Store
        catalog = Catalog(app.config['GEOSERVER_REST_URL'], app.config['GEOSERVER_USER'], app.config['GEOSERVER_PASS'])
        new_store = catalog.create_datastore(store,store)
        new_store.connection_parameters.update(host=app.config['DATASTORE_HOST'], port=app.config['DATASTORE_PORT'], database=store,user=app.config['DATASTORE_USER'], passwd=app.config['DATASTORE_PASS'], dbtype='postgis', schema='public')
        catalog.save(new_store)
        catalog.reload()
        return jsonify({'RTN': 'Store PostGIS ' + store + ' dibuat.'})
    return jsonify({'RTN': 'Permintaan salah!'})

@app.route('/api/store/modify')
# @auth.login_required
def modify_store():
    return jsonify({'RTN': 'Hello!'})

@app.route('/api/store/delete')
# @auth.login_required
def delete_store():
    return jsonify({'RTN': 'Hello!'})    

@app.route('/api/layergroup/add')
# @auth.login_required
def add_layergroup():
    return jsonify({'RTN': 'Hello!'})

@app.route('/api/layergroup/modify')
# @auth.login_required
def modify_layergroup():
    return jsonify({'RTN': 'Hello!'})

@app.route('/api/layergroup/delete')
# @auth.login_required
def delete_layergroup():
    return jsonify({'RTN': 'Hello!'})      
    
@app.route('/api/upload', methods=['POST'])
# @auth.login_required
def upload_file():
    if request.method == 'POST':
        # check if the post request has the file part
        user = request.args.get('USER')
        grup = request.args.get('GRUP')
        print 'User:',user, 'Grup:', grup
        if 'file' not in request.files:
            print 'No file part' 
            resp = json.dumps({'MSG': 'No file part'})
            return Response(resp, mimetype='application/json')
        file = request.files['file']
        print file
        # if user does not select file, browser also
        # submit a empty part without filename
        if file.filename == '':
            print 'No selected file' 
            resp = json.dumps({'RTN': 'ERR', 'MSG': 'No selected file'})
            return Response(resp, status=405, mimetype='application/json')
        if not allowed_file(file.filename):
            resp = json.dumps({'RTN': 'ERR', 'MSG': 'Type not allowed'})
            return Response(resp, status=405, mimetype='application/json')
        if file and allowed_file(file.filename):
            filename = secure_filename(file.filename)
            file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
            unzip(filename,filename)
            for f in app.config['UPLOAD_FOLDER'] + '/' + filename.split('.')[0]:
                path, ext = os.path.splitext(f)
                if ext.isupper():
                    os.rename(f, path + ext.lower())
            for berkas in os.listdir(app.config['UPLOAD_FOLDER'] + '/' + filename.split('.')[0]):
                if berkas.endswith(".tif") or berkas.endswith(".TIF") or berkas.endswith(".tiff") or berkas.endswith(".TIFF"):
                    print "Filename: " + filename.split('.')[0]
                    populate = populateRS(filename.split('.')[0])
                    lid = populate[2]
                    resp = json.dumps({'RTN': filename, 'MSG': 'RASTER Upload Success! Detected projection: ' + populate[1], 'EPSG': populate[1], 'ID': populate[2], 'UUID': populate[3], 'TIPE': populate[4], 'USER': user, 'GRUP': grup, 'LID': lid.lower().replace('-','_')})
                    return Response(resp, mimetype='application/json')                    
                if berkas.endswith(".shp") or berkas.endswith(".SHP"):
                    shapefile = app.config['UPLOAD_FOLDER'] + filename.split('.')[0] + '/' + filename.split('.')[0] + '.shp'
                    print "Shapefile: " + shapefile
                    if os.path.exists(shapefile):
                        print "File SHP OK"
                        populate = populateDB(filename,grup)
                        lid = populate[2]+'-'+populate[3]
                        resp = json.dumps({'RTN': filename, 'MSG': 'Vector Upload Success!' + populate[0], 'EPSG': populate[1], 'ID': populate[2], 'UUID': populate[3], 'TIPE': populate[4], 'USER': user, 'GRUP': grup, 'LID': lid.lower().replace('-','_')})
                        return Response(resp, mimetype='application/json')
                    else:
                        resp = json.dumps({'RTN': 'ERR', 'MSG': 'No SHAPE file!'})
                        return Response(resp, status=405, mimetype='application/json')
        resp = json.dumps({'RTN': 'ERR', 'MSG': 'ERROR'})
        return Response(resp, mimetype='application/json')
        
@app.route('/api/uploads/<string:filename>')
# @auth.login_required
def uploaded_file(filename):
    return send_from_directory(app.config['UPLOAD_FOLDER'],filename)

@app.route('/api/proxy/<path:url>')
def home(url):
    req = request.args.get(url)
    return req

@app.route('/api/feature/<string:feature>/<string:identifier>')
def return_feature(feature, identifier):
    return jsonify({'RTN': feature + ' ' + identifier})

@app.route('/api/publish', methods=['POST'])
def return_publish():
    if request.method == 'POST':
        header = json.loads(urllib2.unquote(request.data).split('=')[1])
        print(header)
        print header['pubdata']['LID']
        tipe = header['pubdata']['TIPE']
        layer_id = header['pubdata']['LID']
        user = header['pubdata']['USER']
        grup = header['pubdata']['GRUP']
        if tipe == 'RASTER':
            catalog = Catalog(app.config['GEOSERVER_REST_URL'], app.config['GEOSERVER_USER'], app.config['GEOSERVER_PASS'])
            workspace = catalog.get_workspace(grup)
            datastore = catalog.get_store(grup)
            # sf = catalog.get_workspace(workspace)
            ft_ext = catalog.create_coveragestore_external_geotiff(layer_id, 'file:'+app.config['RASTER_STORE']+layer_id+'.tif', workspace)
            resource = catalog.get_resources(layer_id)
            resource[0].title = urllib2.unquote(header['pubdata']['ID'])
            resource[0].abstract = urllib2.unquote(header['pubdata']['ABS'])
            resource[0].enabled = True
            resource[0].projection = header['pubdata']['EPSG']
            catalog.save(resource[0])
            catalog.reload()
        if tipe == 'VECTOR':
            catalog = Catalog(app.config['GEOSERVER_REST_URL'], app.config['GEOSERVER_USER'], app.config['GEOSERVER_PASS'])
            workspace = catalog.get_workspace(grup)
            datastore = catalog.get_store(grup)
            publish = catalog.publish_featuretype(header['pubdata']['LID'], datastore, header['pubdata']['EPSG'])
            publish.title = urllib2.unquote(header['pubdata']['ID'])
            publish.abstract = urllib2.unquote(header['pubdata']['ABS'])
            catalog.save(publish)
            catalog.reload()
        metalinks = Metalinks(identifier=layer_id)
        metalinks.workspace = grup
        db.session.add(metalinks)
        db.session.commit()
        wms = WebMapService(app.config['GEOSERVER_WMS_URL'], version='1.1.1')
        bbox = wms[grup+':'+layer_id].boundingBoxWGS84       
        print 'BBOX:', bbox
        thumbnail = wms.getmap(layers=[header['pubdata']['LID']],srs=header['pubdata']['EPSG'],bbox=bbox,size=(300,300),format='image/png',transparent=True)
	file = app.config['GEOSERVER_THUMBNAILS'] + layer_id+'.png'
	print 'File:', file
        outfile = open(file, 'wb')
        outfile.write(thumbnail.read())
        outfile.close()
        resp = json.dumps({'RTN': 'ERR', 'MSG': 'Publikasi layer ke GeoServer Sukses'})
        return Response(resp, mimetype='application/json')
    resp = json.dumps({'RTN': 'ERR', 'MSG': 'POST ERROR'})
    return Response(resp, mimetype='application/json')    

@app.route('/api/checkworkspace', methods=['POST'])
def checkworkspace():
    if request.method == 'POST':
        header = json.loads(urllib2.unquote(request.data).split('=')[1])    
        wrk = header['pubdata']['workspace']
        print wrk
        catalog = Catalog(app.config['GEOSERVER_REST_URL'], app.config['GEOSERVER_USER'], app.config['GEOSERVER_PASS'])
        workspace = catalog.get_workspace(wrk)
        if workspace is None:
            resp = json.dumps({'RTN': 'NA'})
        else:
            resp = json.dumps({'RTN': 'OK'})
        return Response(resp, mimetype='application/json')  

@app.route('/api/kugitogeo')
def kugitogeo():
    list_kugipub = User.query.with_entities(Group.name, Group.enabled)
    groups = GroupSchema(many=True)
    output = groups.dump(list_group)
    resp = json.dumps({'RTN': 'ERR', 'MSG': 'POST ERROR'})
    return Response(resp, mimetype='application/json')    

@app.route('/api/publishkugi', methods=['POST'])
def return_publishkugi():
    if request.method == 'POST':
        header = json.loads(urllib2.unquote(request.data).split('=')[1])
        print(header)
        skema = header['pubdata']['skema']
        fitur = header['pubdata']['fitur']
        dest_db = header['pubdata']['dest_db']
        try:
            catalog = Catalog(app.config['GEOSERVER_REST_URL'], app.config['GEOSERVER_USER'], app.config['GEOSERVER_PASS'])
            workspace = catalog.get_workspace('KUGI')
            datastore = catalog.get_store('KUGI')
            publish = catalog.publish_featuretype(fitur, datastore, 'EPSG:4326')
            publish.title = urllib2.unquote(fitur)
            publish.abstract = urllib2.unquote(fitur)
            catalog.save(publish)
            catalog.reload()
            identifier = 'KUGI:' + fitur
            metakugi = Metakugi(identifier=identifier)
            metakugi.workspace = 'KUGI'
            metakugi.skema = skema
            metakugi.fitur = fitur
            metakugi.tipe = 'induk'
            engine = create_engine(app.config['SQLALCHEMY_BINDS']['dbdev'])
            result = engine.execute("select feature, dataset, fileidentifier from a_view_fileidentifier where feature='" + fitur + "' group by feature, dataset, fileidentifier")
            try:
                for row in result:
                    anakidentifier = 'KUGI:' + fitur + '_' + row[2]
                    anakmetakugi = Metakugi(identifier=anakidentifier)
                    anakmetakugi.workspace = 'KUGI'
                    anakmetakugi.skema = skema
                    anakmetakugi.fitur = fitur
                    anakmetakugi.tipe = 'anak'
                    db.session.add(anakmetakugi)
            except:
                resp = json.dumps({'MSG': 'ERROR'})            
            db.session.add(metakugi)
            db.session.commit()            
            resp = json.dumps({'RTN': 'OK', 'MSG': 'Publikasi layer ke GeoServer Sukses'})
        except:
            resp = json.dumps({'RTN': 'ERR', 'MSG': 'POST ERROR'})
        return Response(resp, mimetype='application/json')

@app.route('/api/cswRecords')
def record_list():
    csw = CatalogueServiceWeb(app.config['CSW_URL'])
    record = {}
    records = []
    try:
        csw.getrecords2(maxrecords=9999999)
        for rec in csw.records:
            record['identifier'] = csw.records[rec].identifier
            record['title'] = csw.records[rec].title
            record['abstract'] = csw.records[rec].abstract
            record['bbox_wgs84'] = csw.records[rec].bbox_wgs84
            record['subjects'] = csw.records[rec].subjects
            record['maxx'] = csw.record[rec].bbox.maxx
            record['maxy'] = csw.record[rec].bbox.maxy
            record['minx'] = csw.record[rec].bbox.minx
            record['miny'] = csw.record[rec].bbox.miny
            records.append(record)
            record = {}
        getrecords = json.dumps(records)
    except:
        getrecords = json.dumps({'ERR':'No Record(s)!'})
    return Response(getrecords, mimetype='application/json')

@app.route('/api/pycswRecords')
def pycsw_records():
    request_param = '?service=CSW&version=2.0.2&request=GetRecords&ElementSetName=full&typenames=csw:Record&resultType=results&outputformat=application/json'
    csw = pycsw_get(app.config['CSW_URL'], request_param)
    # print csw
    record = {}
    records = []    
    try:
        for rec in csw['csw:GetRecordsResponse']['csw:SearchResults']['csw:Record']:
            # print rec['ows:BoundingBox']['ows:UpperCorner'].split(' ')[0]
            try:
                record['identifier'] = rec['dc:identifier']
            except:
                pass
            try:
                record['title'] = rec['dc:title']
            except:
                pass
            try:
                record['abstract'] = rec['dct:abstract']
            except:
                pass
            try:
                record['type'] = rec['dc:type']
            except:
                pass
            # record['subjects'] = csw.records[rec].subjects
            try:
                record['maxx'] = rec['ows:BoundingBox']['ows:UpperCorner'].split(' ')[0]
            except:
                pass
            try:
                record['maxy'] = rec['ows:BoundingBox']['ows:UpperCorner'].split(' ')[1]
            except:
                pass
            try:
                record['minx'] = rec['ows:BoundingBox']['ows:LowerCorner'].split(' ')[0]
            except:
                pass
            try:
                record['miny'] = rec['ows:BoundingBox']['ows:LowerCorner'].split(' ')[1]
            except:
                pass
            try:
                record['thumbnails'] = record['identifier'].split(':')[1]
            except:
                pass
            try:
                for ref in rec['dct:references']:
                    if ref['@scheme'] == 'OGC:WMS':
                        record['WMS'] = 'OGC:WMS'
                    if ref['@scheme'] == 'OGC:WFS':
                        record['WFS'] = 'OGC:WFS'
            except:
                pass        
            records.append(record)
            record = {}
        print records    
        getrecords = json.dumps(records)
        print getrecords
    except:
        getrecords = json.dumps({'ERR':'No Record(s)!'})
    return Response(getrecords, mimetype='application/json')   

@app.route('/api/pycswRecord/insert', methods=['POST'])
def pycsw_insert():
    if request.method == 'POST':
        header = json.loads(urllib2.unquote(request.data).split('=')[1])
        xml_payload = urllib2.unquote(header['pubdata']['xml'])
        identifier = header['pubdata']['identifier']
        workspace = header['pubdata']['workspace']
        akses = header['pubdata']['akses']
        print "Identifier:", header['pubdata']['identifier']
        print "Workspace:", header['pubdata']['workspace']
        print "Akses:", header['pubdata']['akses']
        if workspace == 'KUGI':
            try:
                tipe = header['pubdata']['tipe']
                fi = identifier
            except:
                pass
        else:
            fi = workspace + ':' + identifier
        mcf_template = parse_big_md(xml_payload)
        try:
            print fi
            if akses == 'PUBLIC':
                restriction = 'unclassified'
            if akses == 'GOVERNMENT':
                restriction = 'restricted'
            if akses == 'PRIVATE':
                restriction = 'confendential'        
            print restriction  
            wms = WebMapService(app.config['GEOSERVER_WMS_URL'], version='1.1.1')
            print wms
            bbox = wms[fi].boundingBoxWGS84
            wb = str(bbox[0])
            sb = str(bbox[1])
            eb = str(bbox[2])
            nb = str(bbox[3])
            bboxwgs84 = wb+','+sb+','+eb+','+nb
            print bboxwgs84
            mcf_template = mcf_template.replace('$$rep:fileIdentifier$$', fi)
            # mcf_template = mcf_template.replace('$$rep:individualName$$', individualName)
            # mcf_template = mcf_template.replace('$$rep:organisationName$$', organisationName)
            # mcf_template = mcf_template.replace('$$rep:dateStamp$$', datestamp)
            # mcf_template = mcf_template.replace('$$rep:title$$', title)
            # mcf_template = mcf_template.replace('$$rep:abstract$$', abstract)
            mcf_template = mcf_template.replace('$$rep:security$$', restriction)
            mcf_template = mcf_template.replace('$$rep:secnote$$', akses)
            mcf_template = mcf_template.replace('$$rep:geoserverwms$$', app.config['GEOSERVER_WMS_URL'])
            mcf_template = mcf_template.replace('$$rep:geoserverwfs$$', app.config['GEOSERVER_WFS_URL'])
            # mcf_template = mcf_template.replace('$$rep:wb84$$', wb)
            # mcf_template = mcf_template.replace('$$rep:sb84$$', sb)
            # mcf_template = mcf_template.replace('$$rep:eb84$$', eb)
            # mcf_template = mcf_template.replace('$$rep:nb84$$', nb)
            mcf_template = mcf_template.replace('$$rep:bboxwgs84$$', bboxwgs84)
            rendered_xml = render_template(mcf_template, schema_local='CP-indonesia')
        except:
            msg = json.dumps({'MSG':'Metadata tidak sesuai standar!'})
        try:
            # print xml_template
            csw = CatalogueServiceWeb(app.config['CSW_URL'])
            cswtrans = csw.transaction(ttype='insert', typename='gmd:MD_Metadata', record=rendered_xml)
            if workspace == 'KUGI':
                metakugi = Metakugi.query.filter_by(identifier=header['pubdata']['identifier']).first()     
                metakugi.published = 'Y'
                db.session.commit()                          
            else:
                metalinks = Metalinks.query.filter_by(identifier=header['pubdata']['identifier']).first()
                metalinks.published = 'Y'
                db.session.commit()
            msg = json.dumps({'MSG':'Succeed!', 'CONTENT': rendered_xml, 'TEMPLATE': mcf_template})
        except:
            msg = json.dumps({'MSG':'Fail!'})
        return Response(msg, mimetype='application/json')

@app.route('/api/pycswRecord/delete')
def pycswRecordDelete():
    if request.method == 'POST':
        header = json.loads(urllib2.unquote(request.data).split('=')[1])   
        print header 
        msg = json.dumps({'MSG':'TEST!'})
    return Response(msg, mimetype='application/json')

@app.route('/api/generate_wms_thumbnails')
def generate_wms_thumbnails():
    wms = WebMapService(app.config['GEOSERVER_WMS_URL'], version='1.1.1')
    list_layer = wms.contents
    for layer in list_layer:
        bbox = wms[layer].boundingBoxWGS84
        srs = 'EPSG:4326'
        try:
            file = app.config['GEOSERVER_THUMBNAILS'] + layer.split(':')[1] + '.png'
        except:
            file = app.config['GEOSERVER_THUMBNAILS'] + layer + '.png'      
        thumbnail = wms.getmap(layers=[layer],srs=srs,bbox=bbox,size=(300,300),format='image/png',transparent=True)
        outfile = open(file, 'wb')
        outfile.write(thumbnail.read())
        outfile.close()        
    msg = json.dumps({'MSG':'Thumbnail generations finished!'})      
    return Response(msg, mimetype='application/json')

@app.route('/api/describeRecord')
def describe_record():
    described_record = {}
    return Response(described_record, mimetype='application/json')

@app.route('/api/kug_kategori')
def kugi_kategori():
    kugi_kategori = {}
    return Response(kugi_kategori, mimetype='application/json')

@app.route('/api/metalist')
def metalist():
    metalist = {}
    return Response(metalist, mimetype='application/json')

@app.route('/api/fitur_tersedia', methods=['POST'])
def fitur_tersedia():
    fitur_tersedia = {}
    return Response(fitur_tersedia, mimetype='application/json')

@app.route('/api/grupfitur')
def grupfitur():
    output = []
    engine = create_engine(app.config['SQLALCHEMY_BINDS']['dbpub'])
    result = engine.execute("select feature, dataset from a_view_fileidentifier group by feature, dataset")
    try:
        for row in result:
            isi = {}
            print row[0], row[1]
            isi['fitur'] = row[0].strip()
            isi['skema'] = row[1].strip()
            output.append(isi)
        resp = json.dumps(output)
    except:
        resp = json.dumps({'MSG': 'ERROR'})
    return Response(resp, mimetype='application/json')

@app.route('/api/kugiappenddata', methods=['POST'])
def kugiappeddata():
    if request.method == 'POST':
        skema = request.args.get('schema')
        fitur = request.args.get('fitur')
        skala = request.args.get('skala')
        user = request.args.get('USER')
        grup = request.args.get('GRUP')        
        print skema, fitur, skala
        # print 'User:',user, 'Grup:', grup
        if 'file' not in request.files:
            print 'No file part' 
            resp = json.dumps({'MSG': 'No file part'})
            return Response(resp, mimetype='application/json')
        file = request.files['file']
        print file
        # if user does not select file, browser also
        # submit a empty part without filename
        if file.filename == '':
            print 'No selected file' 
            resp = json.dumps({'RTN': 'ERR', 'MSG': 'No selected file'})
            return Response(resp, status=405, mimetype='application/json')
        if not allowed_file(file.filename):
            resp = json.dumps({'RTN': 'ERR', 'MSG': 'Type not allowed'})
            return Response(resp, status=405, mimetype='application/json')
        if file and allowed_file(file.filename):
            filename = secure_filename(file.filename)
            file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
            unzip(filename,filename)
            for f in app.config['UPLOAD_FOLDER'] + '/' + filename.split('.')[0]:
                path, ext = os.path.splitext(f)
                if ext.isupper():
                    os.rename(f, path + ext.lower())
            for berkas in os.listdir(app.config['UPLOAD_FOLDER'] + '/' + filename.split('.')[0]):
                if berkas.endswith(".tif") or berkas.endswith(".TIF") or berkas.endswith(".tiff") or berkas.endswith(".TIFF"):
                    print "Filename: " + filename.split('.')[0]
                    populate = populateRS(filename.split('.')[0])
                    lid = populate[2]
                    resp = json.dumps({'RTN': filename, 'MSG': 'RASTER Upload Success! Detected projection: ' + populate[1], 'EPSG': populate[1], 'ID': populate[2], 'UUID': populate[3], 'TIPE': populate[4], 'USER': user, 'GRUP': grup, 'LID': lid.lower().replace('-','_')})
                    return Response(resp, mimetype='application/json')                    
                if berkas.endswith(".shp") or berkas.endswith(".SHP"):
                    shapefile = app.config['UPLOAD_FOLDER'] + filename.split('.')[0] + '/' + filename.split('.')[0] + '.shp'
                    print "Shapefile: " + shapefile
                    if os.path.exists(shapefile):
                        print "File SHP OK"
                        populate = populateKUGI(filename, 'palapa_dev', skema, fitur, skala)
                        refresh_dbmetafieldview('dbdev')
                        lid = populate[2]+'-'+populate[3]
                        resp = json.dumps({'RTN': filename, 'MSG': 'Vector Upload Success!' + populate[0], 'EPSG': populate[1], 'ID': populate[2], 'UUID': populate[3], 'TIPE': populate[4], 'OGR': populate[5], 'USER': user, 'GRUP': grup, 'LID': lid.lower().replace('-','_')})
                        return Response(resp, mimetype='application/json')
                    else:
                        resp = json.dumps({'RTN': 'ERR', 'MSG': 'No SHAPE file!'})
                        return Response(resp, status=405, mimetype='application/json')
        resp = json.dumps({'RTN': 'ERR', 'MSG': 'ERROR'})
        return Response(resp, mimetype='application/json')

@app.route('/api/refresh_dbmetaview', methods=['POST'])
def refresh_dbmetaview():
    if request.method == 'POST':
        header = json.loads(urllib2.unquote(request.data).split('=')[1])
        print "Header", header['pubdata'] 
        dbkugi = header['pubdata']['dbkugi']
        # dbkugi = request.args.get('dbkugi')
        try:
            refresh_dbmetafieldview(dbkugi)
            resp = json.dumps({'RTN': 'Success', 'MSG': 'Refreshed!'})
        except:
            resp = json.dumps({'RTN': 'Error', 'MSG': 'Terjadi Kesalahan!'})      
    return Response(resp, mimetype='application/json')         

@app.route('/api/dbdevfeature')
def dbdevfeature():
    output = {}
    engine = create_engine(app.config['SQLALCHEMY_BINDS']['dbdev'])
    result_skala = engine.execute("select skala from a_view_feature group by skala")
    for skala in result_skala:
        result_kategori = engine.execute("select dataset from a_view_feature where skala = %s group by dataset" , skala)
        # print skala[0]
        output[skala[0]] = {}
        for kategori in result_kategori:
            # print "\t", kategori[0]
            sql ="select kategori from a_view_feature where skala = '%s' and dataset = '%s' group by kategori" % (str(skala[0]), str(kategori[0]))
            result_fitur = engine.execute(sql)
            output[skala[0]][kategori[0]] = []
            for fitur in result_fitur:
                # print "\t\t", fitur[0]
                output[skala[0]][kategori[0]].append(fitur[0])
    return Response(json.dumps(output), mimetype='application/json')

@app.route('/api/dbdevisifeature')
def dbdevisifeature():
    output = {}
    outputs = []
    engine = create_engine(app.config['SQLALCHEMY_BINDS']['dbdev'])
    result = engine.execute("select * from a_view_fileidentifier")    
    for row in result:
        output['id'] = row['id']
        output['feature'] = row['feature'].strip()
        output['iddataset'] = row['iddataset']
        output['idkategori'] = row['idkategori']
        output['idskala'] = row['idskala']
        output['dataset'] = row['dataset']
        output['kategori'] = row['kategori']
        output['tipe'] = row['tipe']
        output['alias'] = row['alias']
        output['skala'] = row['skala']
        output['identifier'] = row['fileidentifier']
        outputs.append(output)
        output = {}
    return Response(json.dumps(outputs), mimetype='application/json')

@app.route('/api/dbprodisifeature')
def dbprodisifeature():
    output = {}
    outputs = []
    engine = create_engine(app.config['SQLALCHEMY_BINDS']['dbprod'])
    result = engine.execute("select * from a_view_fileidentifier")    
    for row in result:
        output['id'] = row['id']
        output['feature'] = row['feature'].strip()
        output['iddataset'] = row['iddataset']
        output['idkategori'] = row['idkategori']
        output['idskala'] = row['idskala']
        output['dataset'] = row['dataset']
        output['kategori'] = row['kategori']
        output['tipe'] = row['tipe']
        output['alias'] = row['alias']
        output['skala'] = row['skala']
        output['identifier'] = row['fileidentifier']
        outputs.append(output)
        output = {}
    return Response(json.dumps(outputs), mimetype='application/json')

@app.route('/api/dbpubisifeature')
def dbpubisifeature():
    output = {}
    outputs = []
    engine = create_engine(app.config['SQLALCHEMY_BINDS']['dbpub'])
    result = engine.execute("select * from a_view_fileidentifier")    
    for row in result:
        output['id'] = row['id']
        output['feature'] = row['feature'].strip()
        output['iddataset'] = row['iddataset']
        output['idkategori'] = row['idkategori']
        output['idskala'] = row['idskala']
        output['dataset'] = row['dataset']
        output['kategori'] = row['kategori']
        output['tipe'] = row['tipe']
        output['alias'] = row['alias']
        output['skala'] = row['skala']
        output['identifier'] = row['fileidentifier']
        outputs.append(output)
        output = {}
    return Response(json.dumps(outputs), mimetype='application/json')

@app.route('/api/kopitable', methods=['POST'])
def kopitable():
    if request.method == 'POST':
        header = json.loads(urllib2.unquote(request.data).split('=')[1])
        source_schema = header['pubdata']['dataset']
        source_table = header['pubdata']['feature']
        dest_schema = header['pubdata']['dataset']
        dest_table = header['pubdata']['feature']
        identifier = header['pubdata']['identifier']
        source_db = header['pubdata']['source_db']
        dest_db = header['pubdata']['dest_db']
        try:
            execute = pgis2pgis(source_db, source_schema, source_table, dest_db, dest_schema, dest_table, identifier)
            refresh_dbmetafieldview('dbprod')
            refresh_dbmetafieldview('dbpub')
            resp = json.dumps({'RTN': 'OK', 'MSG': 'Sukses!'})
        except:
            resp = json.dumps({'RTN': 'ERR', 'MSG': 'Gagal!'})
    return Response(json.dumps(resp), mimetype='application/json')

@app.route('/api/meta/view')
# @auth.login_required
def meta_view():
    metalink = Metalinks.query.filter_by(identifier=request.args['identifier']).first()
    xml = metalink.xml
    return Response(xml, mimetype='application/xml')    

@app.route('/api/metakugi/view')
# @auth.login_required
def metakugi_view():
    metalink = Metakugi.query.filter_by(identifier=request.args['identifier']).first()
    xml = metalink.xml
    return Response(xml, mimetype='application/xml')        

@app.route('/api/meta/list')
# @auth.login_required
def meta_list():
    metalist = Metalinks.query.with_entities(Metalinks.workspace, Metalinks.identifier, Metalinks.metatick, Metalinks.published, Metalinks.akses)
    metalinks = MetalinksSchema(many=True)
    output = metalinks.dump(metalist)
    return json.dumps(output.data)    

@app.route('/api/metakugi/list')
# @auth.login_required
def kugi_list():
    metalist = Metakugi.query.with_entities(Metakugi.skema, Metakugi.fitur, Metakugi.workspace, Metakugi.identifier, Metakugi.metatick, Metakugi.published, Metakugi.akses, Metakugi.tipe)
    metalinks = MetakugiSchema(many=True)
    output = metalinks.dump(metalist)
    return json.dumps(output.data)    


@app.route('/api/meta/link', methods=['POST'])
# @auth.login_required
def add_link():
    if request.method == 'POST':
        # check if the post request has the file part
        if 'file' not in request.files:
            print 'No file part' 
            resp = json.dumps({'MSG': 'No file part'})
            return Response(resp, mimetype='application/json')
        file = request.files['file']
        print file
        print 'Param:', request.args['identifier'], request.args['akses']
        # if user does not select file, browser also
        # submit a empty part without filename
        if file.filename == '':
            print 'No selected file' 
            resp = json.dumps({'RTN': 'ERR', 'MSG': 'No selected file'})
            return Response(resp, status=405, mimetype='application/json')
        if not allowed_xml(file.filename):
            resp = json.dumps({'RTN': 'ERR', 'MSG': 'Type not allowed'})
            return Response(resp, status=405, mimetype='application/json')
        if file and allowed_xml(file.filename):
            filename = secure_filename(file.filename)
            file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
            print "Filename: " + filename.split('.')[0]
            xmlfile = app.config['UPLOAD_FOLDER'] + filename.split('.')[0] + '.xml'
            print "XML: " + xmlfile
            if os.path.exists(xmlfile):
                print "File XML OK"
                catalog = Catalog(app.config['GEOSERVER_REST_URL'], app.config['GEOSERVER_USER'], app.config['GEOSERVER_PASS'])
                xml = open(os.path.join(app.config['UPLOAD_FOLDER'], filename))
                try:
                    with open (xmlfile, 'r') as thefile:
                        isixml = thefile.read()
                    metalinks = Metalinks.query.filter_by(identifier=request.args['identifier']).first()
                    metalinks.xml = isixml
                    metalinks.metatick = 'Y'
                    metalinks.akses = request.args['akses']
                    # db.session.add(metalinks)
                    db.session.commit()
                    # catalog.create_style(filename.split('.')[0], xml.read()) 
                    resp = json.dumps({'RTN': filename, 'MSG': 'Upload metadata sukses!'})
                except:
                    resp = json.dumps({'RTN': filename, 'MSG': 'Error, metadata dengan identifier yang sama sudah ada!'})
                return Response(resp, mimetype='application/json')
            else:
                resp = json.dumps({'RTN': 'ERR', 'MSG': 'No SHAPE file!'})
                return Response(resp, status=405, mimetype='application/json')
        resp = json.dumps({'RTN': 'ERR', 'MSG': 'POST ERROR'})
        return Response(resp, mimetype='application/json')    
    # return jsonify({'RTN': 'Hello!'})

@app.route('/api/metakugi/link', methods=['POST'])
# @auth.login_required
def add_kugilink():
    if request.method == 'POST':
        # check if the post request has the file part
        if 'file' not in request.files:
            print 'No file part' 
            resp = json.dumps({'MSG': 'No file part'})
            return Response(resp, mimetype='application/json')
        file = request.files['file']
        print file
        print 'Param:', request.args['identifier'], request.args['akses']
        # if user does not select file, browser also
        # submit a empty part without filename
        if file.filename == '':
            print 'No selected file' 
            resp = json.dumps({'RTN': 'ERR', 'MSG': 'No selected file'})
            return Response(resp, status=405, mimetype='application/json')
        if not allowed_xml(file.filename):
            resp = json.dumps({'RTN': 'ERR', 'MSG': 'Type not allowed'})
            return Response(resp, status=405, mimetype='application/json')
        if file and allowed_xml(file.filename):
            filename = secure_filename(file.filename)
            file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
            print "Filename: " + filename.split('.')[0]
            xmlfile = app.config['UPLOAD_FOLDER'] + filename.split('.')[0] + '.xml'
            print "XML: " + xmlfile
            if os.path.exists(xmlfile):
                print "File XML OK"
                catalog = Catalog(app.config['GEOSERVER_REST_URL'], app.config['GEOSERVER_USER'], app.config['GEOSERVER_PASS'])
                xml = open(os.path.join(app.config['UPLOAD_FOLDER'], filename))
                try:
                    with open (xmlfile, 'r') as thefile:
                        isixml = thefile.read()
                    metakugi = Metakugi.query.filter_by(identifier=request.args['identifier']).first()
                    metakugi.xml = isixml
                    metakugi.metatick = 'Y'
                    metakugi.akses = request.args['akses']
                    # db.session.add(metalinks)
                    db.session.commit()
                    # catalog.create_style(filename.split('.')[0], xml.read()) 
                    resp = json.dumps({'RTN': filename, 'MSG': 'Upload metadata sukses!'})
                except:
                    resp = json.dumps({'RTN': filename, 'MSG': 'Error, metadata dengan identifier yang sama sudah ada!'})
                return Response(resp, mimetype='application/json')
            else:
                resp = json.dumps({'RTN': 'ERR', 'MSG': 'No SHAPE file!'})
                return Response(resp, status=405, mimetype='application/json')
        resp = json.dumps({'RTN': 'ERR', 'MSG': 'POST ERROR'})
        return Response(resp, mimetype='application/json')    
    # return jsonify({'RTN': 'Hello!'})

    # APP MAIN RUNTIME

if __name__ == '__main__':
    if not os.path.exists('gs_db.sqlite'):
        db.create_all()
    app.run(debug=True, passthrough_errors=False)