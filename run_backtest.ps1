# Usage: .\run_backtest.ps1 -trader path\to\trader.py -dataset tutorial
param (
    [string]$trader = "",
    [string]$dataset = "",
    [string]$day = "",
    [switch]$persist,
    [switch]$carry,
    [switch]$flat
)

$cmd = "/mnt/c/Users/peter/Desktop/IMC/imc-prosperity-4/backtester/target/release/rust_backtester"

if ($trader) {
    # Convert windows path to wsl path
    $wslTrader = $trader -replace 'C:\\', '/mnt/c/' -replace '\\', '/'
    $cmd += " --trader $wslTrader"
}

if ($dataset) {
    # if dataset is a path, convert it
    if ($dataset -match ':') {
        $wslDataset = $dataset -replace 'C:\\', '/mnt/c/' -replace '\\', '/'
        $cmd += " --dataset $wslDataset"
    } else {
        $cmd += " --dataset $dataset"
    }
}

if ($day) {
    $cmd += " --day $day"
}

if ($persist) {
    $cmd += " --persist"
}

if ($carry) {
    $cmd += " --carry"
}

if ($flat) {
    $cmd += " --flat"
}

wsl bash -c "$cmd"
