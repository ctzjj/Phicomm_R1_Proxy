<?php
/**
 * 语音劫持
 * host asrv3.hivoice.cn 解析到你的服务器
 * port 80
 * 这个域名有两个连接类型 http  tcp（websocket？）
 */

use Swoole\Coroutine\Client;
use App\Util\DataUtil;
use App\Provider\MusicProvider;
use function Swoole\Coroutine\run;

$server = new Swoole\Server('0.0.0.0', 80);

function client ($server, $fd, $data) {
    $client = new Client(SWOOLE_SOCK_TCP);
    $client->set(array(
        'open_length_check'   => true,
        'dispatch_mode'       => 1,
        'package_length_func' => function ($data) {
            preg_match('#.*Content-Length: (\d+)\r\n\r\n#isU', $data, $matched);
            $headerLen = mb_strlen($matched[0]) ?? 0;
            $bodyLen = $matched[1] ?? 0;
            return intval($headerLen + $bodyLen);
        },
        'package_max_length'  => 1024 * 1024 * 5,
    ));
    if (!$client->connect('47.102.50.144', 80, -1))
    {
        echo "connect failed. Error: {$client->errCode}\n";
    }
    $client->send($data);
    $recv =  $client->recv();
    // file_put_contents('./recv.log', $recv, FILE_APPEND);
     echo $recv;
    $dataUtil = new DataUtil($recv);
    $musicProvider = new MusicProvider($dataUtil);
    if ($musicProvider->isMusic()) {
        $musicProvider->search();
    }
    $data = $dataUtil->build();
    echo $data;
    $server->send($fd, $data);
    $client->close();
}

$server->on('WorkerStart', function($server, $workerId) {
    include_once "./vendor/autoload.php";
});


$server->on('Connect', function ($server, $fd) {

});


$server->on('Receive', function ($server, $fd, $reactor_id, $data) {
    // var_dump($data);
    client($server, $fd, $data);
});


$server->on('Close', function ($server, $fd) {

});

//启动服务器
$server->start();