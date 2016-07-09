# -*- coding: utf-8 -*-

import pymongo
import urllib2
ASC = pymongo.ASCENDING
DESC = pymongo.DESCENDING
import flask
import yaml
import lmfdb.base as base
from lmfdb.utils import flash_error
from datetime import datetime
from flask import render_template, request, url_for
from lmfdb.api import api_page, api_logger
from bson.objectid import ObjectId

# caches the database information
_databases = None

def pluck(n, list):
    return [_[n] for _ in list]

def quote_string(value):
    if isinstance(value,unicode) or isinstance(value,str):
        return repr(value)
    elif isinstance(value,ObjectId):
        return "\"ObjectId('%s')\""%value
    return value

def pretty_document(rec,sep=", ",id=True):
    # sort keys and remove _id for html display
    attrs = sorted([(key,quote_string(rec[key])) for key in rec.keys() if (id or key != '_id')])
    return "{"+sep.join(["'%s': %s"%attr for attr in attrs])+"}"


def censor(entries):
    """
    hide some of the databases and collection from the public
    """
    dontstart = ["system.", "test", "upload", "admin", "contrib"]
    censor = ["local", "userdb"]
    for entry in entries:
        if any(entry == x for x in censor) or \
           any(entry.startswith(x) for x in dontstart):
            continue
        yield entry

def init_database_info():
    global _databases
    if _databases is None:
        C = base.getDBConnection()
        _databases = {}
        for db in censor(C.database_names()):
            colls = list(censor(C[db].collection_names()))
            _databases[db] = sorted([(c, C[db][c].count()) for c in colls])

@api_page.route("/")
def index():
    init_database_info()
    databases = _databases
    title = "API"
    return render_template("api.html", **locals())

@api_page.route("/stats")
def stats():
    def mb(x):
        return round(x/1000000.0)
    init_database_info()
    C = base.getDBConnection()
    dbstats = {db:C[db].command("dbstats") for db in _databases}
    dbs = len(dbstats.keys())
    collections = 0
    objects = 0
    size = 0
    stats = {}
    for db in dbstats:
        dbsize = dbstats['dataSize']+dbstats[db]['indexSize']
        size += dbsize
        dbsize = mb(dbsize)
        if dbsize:
            stats[db] = {'db':db, 'coll':'', 'dbSize':dbsize, 'size':dbsize, 'dataSize':mb(dbstats[db]['dataSize']), 'indexSize':mb(dbstats[db]['indexSize']),
                         'avgObjSize':round(dbstats[db]['avgObjSize']), 'objects':dbstats[db]['objects']}
        for c in pluck(0,_databases[db]):
            if C[db][c].count():
                collections += 1
                coll = '<a href = "' + url_for (".api_query", db=db, collection = c) + '>c</a>'
                cstats = C[db].command("collstats",c)
                objects += cstats['count']
                csize = mb(cstats['size']+cstats['totalIndexSize'])
                if csize:
                    stats[cstats['ns']] = {'db':db, 'coll':coll, 'dbSize': dbsize, 'size':size,
                                          'dataSize':mb(cstats['size']), 'indexSize':mb(cstats['totalIndexSize']), 'avgObjSize':round(cstats['avgObjSize']), 'objects':cstats['count']}
    sortedkeys = sorted([db for db in stats],key=lambda x: (-stats[x]['dbSize'],stats[x]['db'],-stats[x]['size'],stats[x]['coll']))
    statslist = [stats[key] for key in sortedkeys]
    return render_template('stats.html', info={'dbs':dbs,'collections':collections,'objects':objects,'size':mb(size),'stats':statslist})

@api_page.route("/<db>/<collection>/<id>")
def api_query_id(db, collection, id):
    return api_query(db, collection, id = id)


@api_page.route("/<db>/<collection>")
def api_query(db, collection, id = None):
    init_database_info()

    # check what is queried for
    if db not in _databases or collection not in pluck(0, _databases[db]):
        return flask.abort(404)

    # parsing the meta parameters _format and _offset
    format = request.args.get("_format", "html")
    offset = int(request.args.get("_offset", 0))
    DELIM = request.args.get("_delim", ",")
    fields = request.args.get("_fields", None)
    sortby = request.args.get("_sort", None)

    if fields:
        fields = fields.split(DELIM)

    if sortby:
        sortby = sortby.split(DELIM)

    if offset > 10000:
        if format != "html":
            flask.abort(404)
        else:
            flash_error("offset %s too large, please refine your query.", offset)
            return flask.redirect(url_for(".api_query", db=db, collection=collection))

    # sort = [('fieldname1', ASC/DESC), ...]
    if sortby is not None:
        sort = []
        for key in sortby:
            if key.startswith("-"):
                sort.append((key[1:], DESC))
            else:
                sort.append((key, ASC))
    else:
        sort = None

    # preparing the actual database query q
    C = base.getDBConnection()
    q = {}

    if id is not None:
        if id.startswith('ObjectId('):
            q["_id"] = ObjectId(id[10:-2])
        else:
            q["_id"] = id
        single_object = True
    else:
        single_object = False

        for qkey, qval in request.args.iteritems():
            from ast import literal_eval
            try:
                if qkey.startswith("_"):
                    continue
                if qval.startswith("s"):
                    qval = qval[1:]
                if qval.startswith("i"):
                    qval = int(qval[1:])
                elif qval.startswith("f"):
                    qval = float(qval[1:])
                elif qval.startswith("ls"):      # indicator, that it might be a list of strings
                    qval = qval[2:].split(DELIM)
                elif qval.startswith("li"):
                    qval = [int(_) for _ in qval[2:].split(DELIM)]
                elif qval.startswith("lf"):
                    qval = [float(_) for _ in qval[2:].split(DELIM)]
                elif qval.startswith("py"):     # literal evaluation
                    qval = literal_eval(qval[2:])
                elif qval.startswith("cs"):     # containing string in list
                    qval = { "$in" : [qval[2:]] }
                elif qval.startswith("ci"):
                    qval = { "$in" : [int(qval[2:])] }
                elif qval.startswith("cf"):
                    qval = { "$in" : [float(qval[2:])] }
                elif qval.startswith("cpy"):
                    qval = { "$in" : [literal_eval(qval[3:])] }
            except:
                # no suitable conversion for the value, keep it as string
                pass

            # update the query
            q[qkey] = qval

    # executing the query "q" and replacing the _id in the result list
    api_logger.info("API query: q = '%s', fields = '%s', sort = '%s', offset = %s" % (q, fields, sort, offset))
    data = list(C[db][collection].find(q, projection = fields, sort=sort).skip(offset).limit(100))
    
    if single_object and not data:
        if format != 'html':
            flask.abort(404)
        else:
            flash_error("no document with id %s found in collection %s.%s.", id, db, collection)
            return flask.redirect(url_for(".api_query", db=db, collection=collection))
    
    for document in data:
        oid = document["_id"]
        if type(oid) == ObjectId:
            document["_id"] = "ObjectId('%s')" % oid
        elif isinstance(oid, basestring):
            document["_id"] = str(oid)

    # preparing the datastructure
    start = offset
    next_req = dict(request.args)
    next_req["_offset"] = offset
    url_args = next_req.copy()
    query = url_for(".api_query", db=db, collection=collection, **next_req)
    offset += len(data)
    next_req["_offset"] = offset
    next = url_for(".api_query", db=db, collection=collection, **next_req)

    # the collected result
    data = {
        "database": db,
        "collection": collection,
        "timestamp": datetime.utcnow().isoformat(),
        "data": data,
        "start": start,
        "offset": offset,
        "query": query,
        "next": next
    }

    # display of the result (default html)
    if format.lower() == "json":
        return flask.jsonify(**data)
    elif format.lower() == "yaml":
        y = yaml.dump(data,
                      default_flow_style=False,
                      canonical=False,
                      allow_unicode=True)
        return flask.Response(y, mimetype='text/plain')
    else:
        # sort displayed records by key (as json and yaml do)
        data["pretty"] = pretty_document
        location = "%s/%s" % (db, collection)
        title = "API - " + location
        bc = [("API", url_for(".index")), (location, query)]
        query_unquote = urllib2.unquote(data["query"])
        return render_template("collection.html",
                               title=title,
                               single_object=single_object,
                               query_unquote = query_unquote,
                               url_args = url_args,
                               bread=bc,
                               **data)

