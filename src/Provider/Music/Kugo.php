<?php


namespace App\Provider\Music;


use GuzzleHttp\Client;

class Kugo
{
    /**
     * @var Client
     */
    private $curl;

    private $headers = [
        'referer' => 'http://songsearch.kugou.com/v3/search',
        'user-agent' => 'Mozilla/5.0 (iPhone; CPU iPhone OS 13_2_3 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/13.0.3 Mobile/15E148 Safari/604.1'
    ];

    public function __construct()
    {
        $this->curl = new Client();
    }

    public function search ($keyword, Format $format)
    {
        $query = [
            'keyword' => urlencode($keyword),
            'page' => '2',
        ];
        $response = $this->curl->get('http://www.kuwo.cn/api/www/search/searchMusicBykeyWord', [
            'headers' => $this->headers,
            'query' => $query
        ]);
        $content = $response->getBody()->getContents();
        var_dump($content);exit;
    }
}