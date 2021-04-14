<?php


namespace App\Util;


class DataUtil
{
    private $httpInfo = [];
    private $bodyLength = 0;

    public function __construct($content)
    {
        $this->parse($content);
    }

    private function parse($content) {
        list($header, $body) = preg_split('#\r\n\r\n#isU', $content);
        $this->httpInfo['header'] = $header . "\r\n\r\n";
        $this->httpInfo['body'] = json_decode($body, true);
        $this->httpInfo['origin'] = $content;
    }

    public function getBody() {
        return $this->httpInfo['body'];
    }

    public function setBody($body) {
        $this->httpInfo['body'] = $body;
    }

    public function build() {
        $bodyStr = $this->httpInfo['body'] ? json_encode($this->httpInfo['body'], JSON_UNESCAPED_SLASHES|JSON_UNESCAPED_UNICODE) : '';
        $bodyLen = strlen($bodyStr);
        $this->httpInfo['header'] = preg_replace('#Content-Length: (\d+)\r\n\r\n#isU', "Content-Length: {$bodyLen}\r\n\r\n", $this->httpInfo['header']) ?? $this->httpInfo['header'];
        return $this->httpInfo['header'] . $bodyStr;
    }
}