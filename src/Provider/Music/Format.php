<?php

/**
 * 目前音乐的格式用的是音频的返回格式，所以没有氛围灯，
 * 如果有人抓到或者知道音乐播放返回的数据格式，
 * 希望可以分享一下
 */

namespace App\Provider\Music;


class Format
{
    private $data = [];

    public function __construct()
    {
        $this->data = array (
            'semantic' =>
                array (
                    'intent' =>
                        array (
                            'language' => 'zh',
                            'tag' => '',
                            'keyword' => '',
                        ),
                ),
            'code' => 'SEARCH_CATEGORY',
            'data' =>
                array (
                    'result' =>
                        array (
                            'count' => 0,
                            'musicinfo' => [],
                            'totalTime' => 10,
                            'pagesize' => '60',
                            'errorCode' => 0,
                            'page' => '1',
                            'source' => 1,
                            'dataSourceName' => '我的音乐',
                        ),
                ),
            'originIntent' =>
                array (
                    'nluSlotInfos' =>
                        array (
                        ),
                ),
            'history' => 'cn.yunzhisheng.music',
            'source' => 'nlu',
            'uniCarRet' =>
                array (
                    'result' =>
                        array (
                        ),
                    'returnCode' => 609,
                    'message' => 'aios-home.hivoice.cn',
                ),
            'asr_recongize' => '播放。',
            'rc' => 0,
            'general' =>
                array (
                    'actionAble' => 'true',
                    'quitDialog' => 'true',
                    'text' => '为您播放',
                    'type' => 'T',
                ),
            'returnCode' => 0,
            'audioUrl' => 'http://asrv3.hivoice.cn/trafficRouter/r/wMgclE',
            'retTag' => 'nlu',
            'service' => 'cn.yunzhisheng.music',
            'nluProcessTime' => '106',
            'text' => '为您播放',
            'responseId' => 'e490d9576c5b438c8283a6e71cdba997',
        );
    }

    public function setSemantic($semantic) {
        $this->data['semantic'] = $semantic;
        return $this;
    }

    public function setDataList(ItemList $itemList) {
        $musicList = $itemList->getDataList();
        if (empty($musicList)) {
            return $this;
        }
        $this->data['data']['result']['musicinfo'] = $musicList;
        return $this;
    }

    public function setText($text) {
        $this->data['text'] = $text;
        return $this;
    }

    public function setAsrText($asrText) {
        $this->data['general']['text'] = $asrText;
        $this->data['asr_recongize'] = $asrText;
        return $this;
    }

    public function setTotal($total) {
        $this->data['data']['result']['count'] = $total;
        return $this;
    }

    public function setPageSize($size) {
        $this->data['data']['result']['pagesize'] = $size;
        return $this;
    }

    public function getData() {
        return $this->data;
    }
}
class ItemList {
    private $data = [];

    public function setDataList(Item $data) {
        $item = $data->getData();
        if (empty($item['url'])) {
            return false;
        }
        array_push($this->data, $item);
    }

    public function getDataList() {
        return $this->data;
    }
}

class Item {
    private $data = [];

    public function __construct()
    {
        mt_srand();
        $this->data = [
            'id' => mt_rand(1, 9999999),
            'errorCode' => 0,
            'duration' => mt_rand(1, 9999999),
            'lyric' => ''
        ];
    }

    public function setAlbum($album) {
        $this->data['album'] = $album;
        return $this;
    }

    public function setArtist($artist) {
        $this->data['artist'] = $artist;
        return $this;
    }

    public function setHdImgUrl($hdImgUrl) {
        $this->data['hdImgUrl'] = $hdImgUrl;
        return $this;
    }

    public function setImgUrl($imgUrl) {
        $this->data['imgUrl'] = $imgUrl;
        return $this;
    }

    public function setIsCollected($isCollected) {
        $this->data['isCollected'] = $isCollected;
        return $this;
    }

    public function setLyric($lyric) {
        $this->data['lyric'] = $lyric;
        return $this;
    }

    public function setTitle($title) {
        $this->data['title'] = $title;
        return $this;
    }

    public function setUrl($url) {
        $this->data['url'] = $url;
        return $this;
    }

    public function getData() {
        return $this->data;
    }
}