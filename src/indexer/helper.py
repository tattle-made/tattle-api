import os
import sys
import numpy as np
from dotenv import load_dotenv
import pymongo
from pymongo import MongoClient
load_dotenv()
import wget
# from search import ImageSearch, TextSearch, DocSearch
from analyzer import ResNet18, detect_text, image_from_url, detect_lang, doc2vec
import cv2
from VideoAnalyzer import VideoAnalyzer, compress_video
from elasticsearch import Elasticsearch
from elasticsearch import helpers as eshelpers
from datetime import datetime
from flask import jsonify 
import uuid
import logging

try:
    # mongo_url = os.environ['MONGO_URL']
    # cli = MongoClient(mongo_url)
    # db = cli[os.environ.get("DB_NAME")]
    # coll = db[os.environ.get("DB_COLLECTION")]
    es_host = os.environ['ES_HOST']
    es_vid_index = os.environ['ES_VID_INDEX']
    es_img_index = os.environ['ES_IMG_INDEX']
    es_txt_index = os.environ['ES_TXT_INDEX']
    
except Exception:
    print(logging.traceback.format_exc())


# imagesearch = ImageSearch()
# docsearch = DocSearch()
# textsearch = TextSearch()
resnet18 = ResNet18()

config = {'host': es_host}
es = Elasticsearch([config,])

def index_data(es, data):

    date = datetime.utcnow()
    doc_id = data['source_id']
    if data["media_type"] == "text":
        text = data["text"]
        lang = detect_lang(text)
        print("Generating document vector")
        text_vec = doc2vec(text)
        print("Document vector generated")

        if text_vec is None:
            text_vec = np.zeros(300).tolist()

        doc = {
                "source_id" : str(doc_id),
                "source" : data.get("source", "tattle-admin"),
                "metadata" : data.get("metadata", {}),
                "text": text,
                "lang": lang,
                "text_vec" : text_vec,
                "date_added": datetime.utcnow().strftime("%d%m%Y")
                    }

        res = es.index(index=es_txt_index, body=doc)
        print("Document vector indexed")

        # Code for verifying that data is indexed
        # es.indices.refresh(es_txt_index)
        # res2 = es.search(
        #     index=es_txt_index, 
        #     body={"query": {
        #             "match": {
        #                 "date_added": datetime.utcnow().strftime("%d%m%Y")}}})
        # print(res2["hits"]["hits"])

        return res
            
    elif data["media_type"] == "image":
        print("data is image")
        image_url = data["file_url"]
        image_dict = image_from_url(image_url)
        image = image_dict['image']
        image = image.convert('RGB') #take care of png(RGBA) issue
        print("Generating image vector")
        image_vec = resnet18.extract_feature(image)
        print("Image vector generated")
        detected_text = detect_text(image_dict['image_bytes']).get('text','')
        lang = detect_lang(detected_text)
        print(lang)
        #import ipdb; ipdb.set_trace()
        if detected_text == '' or None:
            text_vec = np.zeros(300).tolist()
            has_text = False
        else:
            print("Generating image text vector")
            text_vec = doc2vec(detected_text)
            print("Image text vector generated ")
            has_text = True

        if lang is None:
            text_vec = np.zeros(300).tolist()
            has_text = True

        if text_vec is None:
            text_vec = np.zeros(300).tolist()
            has_text = True

        combined_vec = np.hstack((image_vec, text_vec)).tolist()

        doc = {
        "source_id" : str(doc_id),
        "source" : data.get("source", "tattle-admin"),
        "metadata" : data.get("metadata", {}),
        "has_text" : has_text,
        "text": detected_text,
        "text_vec" : text_vec,
        "lang": lang,
        "image_vec": image_vec,
        "combined_vec": combined_vec,
        "date_added": date
            }

        res = es.index(index=es_img_index, body=doc)
        print("Image vector indexed")
        return res


    elif data["media_type"] == "video":
        print("data is video")
        fname = '/tmp/vid.mp4'
        print("Downloading video from url")
        video_url = data["file_url"]

        wget.download(video_url, out=fname)
        print("video downloaded")
        # fsize in MB
        fsize = os.path.getsize(fname)/1e6
        print("original size: ", fsize)
        if fsize > 10:
            print("compressing video")
            fname = compress_video(fname)
            fsize = os.path.getsize(fname)/1e6
            print("compressed video size: ", fsize)
        if fsize > 10:
            raise Exception("Video too large")
        video = cv2.VideoCapture(fname)
        # print(type(video))
        vid_analyzer = VideoAnalyzer(video)
        # print(vid_analyzer)
        vid_analyzer.set_fsize(fsize)

        doable, error_msg = vid_analyzer.check_constraints()
        # print(doable)
        # print(error_msg)
        if not doable:
            print(jsonify({'failed' : 1, 'error' : error_msg}))
            return jsonify({'failed' : 1, 'error' : error_msg})

        def gendata(vid_analyzer):
            for i in range(vid_analyzer.n_keyframes):
                yield {
                    "_index": es_vid_index,
                    "source_id" : str(doc_id),
                    "source" : data.get("source", "tattle-admin"),
                    "metadata" : data.get("metadata", {}),
                    "vid_vec" : vid_analyzer.keyframe_features[:,i].tolist(),
                    "is_avg" : False,
                    "date_added": date,
                    "duration" : vid_analyzer.duration,
                    "n_keyframes" : vid_analyzer.n_keyframes,
                    }

            yield {
                    "_index": es_vid_index,
                    "source_id" : str(doc_id),
                    "source" : data.get("source", "tattle-admin"),
                    "metadata" : data.get("metadata", {}),
                    "vid_vec" : vid_analyzer.get_mean_feature().tolist(),
                    "is_avg" : True,
                    "date_added": date,
                    "duration" : vid_analyzer.duration,
                    "n_keyframes" : vid_analyzer.n_keyframes,
                    }
        
        print("Generating video vectors")
        res = eshelpers.bulk(es, gendata(vid_analyzer))
        print("Video vectors indexed")
        os.remove(fname)
        return res

if __name__ == "__main__":
    data = {
        "source_id": "123",
        "media_type": "image",
        "file_url": "https://s3.ap-south-1.amazonaws.com/sharechat-scraper.tattle.co.in/000021a7-905b-4e0a-a48e-b58b8fc305bc.jpg",
        "metadata": {"test": "image indexing"}
    }
    index_data(es, data)