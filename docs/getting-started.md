# Getting started

The client is free. It runs on your computer. It does not hold your money.

## What an API key is

An API key is a password your exchange gives to a program. Krellbot uses it to ask Kraken what to do. The key stays in a file on your machine. krellbot.dev never receives it.

## Turn trade on. Turn withdraw off.

You need a Kraken account before a pack can place an order. You do not need one to read these docs or to install the client.

When you create the Kraken key:

- Trade permission on.
- Withdraw permission off.

Coinbase is not ready. Do not make a Coinbase key for this client yet.

## Install the free client

On a Mac:

```
curl -fsSL https://krellbot.dev/api/install?os=mac | sh
```

On Windows, Python is required. The install command is on the home page.

## What a pack is

A pack is a JSON file. The format is open. You can write your own and put it in `~/.krellbot/packs/`. The client reads the file. It does not run code inside it.

The packs we maintain are a separate download. Those names stay off the public page. $39 a month downloads them.

```
krellbot setup <license-key>
```

A pack you write does not need that key.

## What a window is

A window is the dates the chart covers. A return without those dates is not a result you can read.

## What a drawdown is

A drawdown is how far the result fell from a high point before it recovered. A high return with a large drawdown is still a large drawdown.

## What it will not do yet

The client will not place an order until that path exists. With no packs, it tells you none are installed. With a pack, it can show that pack's past history. That history is not a Krellbot fill.
