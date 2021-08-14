<?php
/**
 * 配网后提示未绑定时，先将 aios-home.hivoice.cn 解析到这个脚本运行的服务器
 * 然后运行脚本，唤醒小讯，没有提示未绑定就成功了，
 * 记得删除掉域名解析，ctrl+c停止脚本
 */

$http = new Swoole\Http\Server('0.0.0.0', 19999);

$http->on('Request', function ($request, $response) {
    echo $request->server['path_info'] || $request->server['request_uri'];
    if ($request->server['path_info'] == '/favicon.ico' || $request->server['request_uri'] == '/favicon.ico') {
        $response->end();
        return;
    }
    $response->header('Content-Type', 'text/plain; charset=UTF-8');
    if ($request->server['path_info'] == '/getUserInfo' || $request->server['request_uri'] == '/getUserInfo') {
        $response->end(json_encode(['status' => '0']));
        return;
    }
    $response->end('<h1>Hello World</h1>');
});

$http->start();