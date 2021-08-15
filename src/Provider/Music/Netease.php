<?php


namespace App\Provider\Music;


use GuzzleHttp\Client;

class Netease
{
    /**
     * @var Client
     */
    private $curl;

    private $headers = [
        'referer' => 'http://music.163.com/',
        'user-agent' => 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.106 Safari/537.36'
    ];

    public function __construct()
    {
        $this->curl = new Client();
    }

    public function search ($keyword, Format $format)
    {
        $pageSize = 20;
        $response = $this->curl->post('http://music.163.com/api/linux/forward', [
            'headers' => $this->headers,
            'form_params' => $this->buildParam([
                'method' => 'POST',
                'url' => 'http://music.163.com/api/cloudsearch/pc',
                'params' => [
                    's'        => $keyword,
                    'type'     => '1',
                    'offset'   => '0',
                    'limit'    => $pageSize
                ]
            ])
        ]);
        $content = $response->getBody()->getContents();
        $songsInfo = json_decode($content, true);
        if (empty($songsInfo)) {
            return $format;
        }
        $format->setPageSize($pageSize);
        $coount = 0;
        $musiclist = new ItemList();
        foreach($songsInfo['result']['songs'] as $song) {
            if ($song['privilege']['fl'] == 0) { //无版权
                continue;
            }
            $url = $this->getSongUrl($song['id']);
            if (empty($url)) {
                continue;
            }
            $item = new Item();
            $item->setAlbum($song['al']['name']);
            $item->setTitle($song['name']);
            $item->setArtist($song['ar'][0]['name']);
            $item->setHdImgUrl($song['al']['picUrl']);
            $item->setLyric('');
            $item->setIsCollected(false);
            $item->setUrl($url);
            $musiclist->setDataList($item);
            $coount++;
        }
        $format -> setTotal($coount);
        $format->setDataList($musiclist);
        return $format;
    }

    private function getSongUrl($id) {
        $response = $this->curl->post('http://music.163.com/api/linux/forward', [
            'headers' => $this->headers,
            'form_params' => $this->buildParam([
                'method' => 'POST',
                'url' => 'http://music.163.com/api/song/enhance/player/url',
                'params' => [
                    'ids' => [$id],
                    'br'  => 320000,
                ]
            ])
        ]);
        $content = $response->getBody()->getContents();
        $urlInfo = json_decode($content, true);
        if (!isset($urlInfo['data']) || !isset($urlInfo['data'][0])) {
            return null;
        }
        $url = $urlInfo['data'][0]['url'];
        return $url;
    }

    private function buildParam($data) {
        $key = '7246674226682325323F5E6544673A51';
        $data = json_encode($data);
        $data = openssl_encrypt($data, 'aes-128-ecb', pack('H*', $key));
        $data = strtoupper(bin2hex(base64_decode($data)));
        return ['eparams' => $data];
    }
}