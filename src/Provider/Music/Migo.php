<?php


namespace App\Provider\Music;

use GuzzleHttp\Client;

class Migo
{
    /**
     * @var Client
     */
    private $curl;

    private $headers = [
        'host' => 'm.music.migu.cn',
        'referer' => 'https://m.music.migu.cn/v3/search',
        'accept' => 'application/json, text/javascript, */*; q=0.01',
        'accept-encoding' => 'gzip, deflate',
        'accept-language' => 'zh-CN,zh;q=0.9',
        'user-agent' => 'Mozilla/5.0 (iPhone; CPU iPhone OS 13_2_3 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/13.0.3 Mobile/15E148 Safari/604.1'
    ];

    public function __construct()
    {
        $this->curl = new Client();
    }

    public function search ($keyword, Format $format) {
        $pageSize = 20;
        $query = [
            'keyword' => urlencode($keyword),
            'type' => '2',
            'rows' => "$pageSize",
            'pgc' => '1'
        ];
        $response = $this->curl->get('https://m.music.migu.cn/migu/remoting/scr_search_tag', [
            'headers' => $this->headers,
            'query' => $query
        ]);
        $content = $response->getBody()->getContents();
        $resp = json_decode($content, true);
        if (empty($resp)) {
            return $format;
        }
        $format -> setTotal(count($resp['musics']));
        $format->setPageSize($pageSize);
        $musiclist = new ItemList();
        foreach ($resp['musics'] as $music) {
            $item = new Item();
            $item->setAlbum($music['albumName']);
            $item->setTitle($music['title']);
            $item->setArtist($music['artist']);
            $item->setHdImgUrl($music['cover']);
            $item->setLyric($music['lyrics']);
            $item->setIsCollected(false);
            $item->setUrl($music['mp3']);
            $musiclist->setDataList($item);
        }
        $format->setDataList($musiclist);
        return $format;
    }

}