<?php

include_once "./vendor/autoload.php";


use App\Provider\Music\Migo;
use App\Provider\Music\Format;

$mg = new \App\Provider\Music\Kugo();
$mg->search('刺猬', new Format());