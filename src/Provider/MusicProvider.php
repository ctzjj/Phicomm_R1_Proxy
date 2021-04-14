<?php
namespace App\Provider;

use App\Util\DataUtil;
use App\Provider\Music\Migo;
use App\Provider\Music\Format;

class MusicProvider
{
    private $dataUtil;

    private $keyword;

    public function __construct(DataUtil $dataUtil)
    {
        $this->dataUtil = $dataUtil;
    }

    public function isMusic() {
        $body = $this->dataUtil->getBody();
        if (empty($body)) {
            return false;
        }
        if ($body['code'] === 'SEARCH_ARTIST') {
            $this->keyword = $body['semantic']['intent']['keyword'];
            return true;
        }

        if ($body['code'] === 'SEARCH_CATEGORY') {
            $this->keyword = $body['semantic']['intent']['keyword'];
            return true;
        }

        if (preg_match('#^我想听(.*)的歌$#isuU', $body['text'], $matched)) {
            $this->keyword = $matched[1];
            return true;
        }

        if (preg_match('#^我想听(.*?)的(.*)#isu', $body['text'], $matched)) {
            $this->keyword = $matched[2] . ' ' . $matched[1];
            return true;
        }

        if (preg_match('#^播放(.*?)的(.*)#isu', $body['text'], $matched)) {
            $this->keyword = $matched[2] . ' ' . $matched[1];
            return true;
        }
        return false;
    }

    public function search() {
        $body = $this->dataUtil->getBody();
        $format = new Format();
        $format->setSemantic($body['semantic']);
        $format->setText($this->keyword)->setAsrText($this->keyword);
        (new Migo())->search($this->keyword, $format);
        $this->dataUtil->setBody($format->getData());
    }
}