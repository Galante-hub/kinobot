import logging
import sqlite3
from random import randint, shuffle

import click
from discord import Embed, User, File
from discord.ext import commands

import kinobot.db as db
from kinobot import DISCORD_TOKEN, MEME_IMG
from kinobot.comments import dissect_comment
from kinobot.exceptions import (
    EpisodeNotFound,
    MovieNotFound,
    OffensiveWord,
    InvalidRequest,
)
from kinobot.request import search_episode, search_movie
from kinobot.utils import get_id_from_discord, is_episode

db.create_discord_db()

bot = commands.Bot(command_prefix="!")

BASE = "https://kino.caretas.club"
RANGE_DICT = {"1️⃣": 0, "2️⃣": 1, "3️⃣": 2, "4️⃣": 3, "5️⃣": 4}
GOOD_BAD = ("👍", "💩")
EMOJI_STRS = ("1️⃣", "2️⃣", "3️⃣", "4️⃣", "5️⃣")


def handle_discord_request(ctx, command, args):
    request = " ".join(args)
    user_disc = ctx.author.name + ctx.author.discriminator
    username = db.get_name_from_discriminator(user_disc)

    try:
        request_dict = dissect_comment(f"!{command} {request}")
    except (MovieNotFound, EpisodeNotFound, OffensiveWord, InvalidRequest) as kino_exc:
        return f"Nope: {type(kino_exc).__name__}."

    request_id = str(randint(2000000, 5000000))

    if not request_dict:
        return "Invalid syntax."
    elif not username:
        return "You are not registered. Use `!register <YOUR NAME>`."

    try:
        db.insert_request(
            (
                username[0],
                request_dict["comment"],
                request_dict["command"],
                request_dict["title"],
                "|".join(request_dict["content"]),
                request_id,
                1,
            )
        )
        db.verify_request(request_id)
        return f"Added. ID: {request_id}; user: {username[0]}."
    except sqlite3.IntegrityError:
        return "Duplicate request."


def handle_queue(queue, title):
    if queue:
        shuffle(queue)
        description = "\n".join(queue[:10])
        return Embed(title=title, description=description)
    return Embed(title=title, description="apoco si pa")


@bot.command(name="req", help="make a regular request")
async def request(ctx, *args):
    message = await ctx.send(handle_discord_request(ctx, "req", args))
    [await message.add_reaction(emoji) for emoji in GOOD_BAD]


@bot.command(name="parallel", help="make a parallel request")
async def parallel(ctx, *args):
    message = await ctx.send(handle_discord_request(ctx, "parallel", args))
    [await message.add_reaction(emoji) for emoji in GOOD_BAD]


@bot.command(name="palette", help="make a palette request")
async def palette(ctx, *args):
    message = await ctx.send(handle_discord_request(ctx, "palette", args))
    [await message.add_reaction(emoji) for emoji in GOOD_BAD]


@bot.command(name="register", help="register yourself")
async def register(ctx, *args):
    name = " ".join(args).title()
    discriminator = ctx.author.name + ctx.author.discriminator
    if not name:
        message = "Usage: `!register <YOUR NAME>`"
    elif not "".join(args).isalpha():
        message = "Invalid name."
    else:
        try:
            db.register_discord_user(name, discriminator)
            message = f"You were registered as '{name}'."
        except sqlite3.IntegrityError:
            old_name = db.get_name_from_discriminator(discriminator)[0]
            try:
                db.update_discord_name(name, discriminator)
                db.update_name_from_requests(old_name, name)
                message = f"Your name was updated: '{name}'."
            except sqlite3.IntegrityError:
                message = "Duplicate name."

    await ctx.send(message)


@bot.command(name="queue", help="get user queue")
async def queue(ctx, user: User = None):
    try:
        if user:
            name = db.get_name_from_discriminator(user.name + user.discriminator)[0]
            queue = db.get_user_queue(name)
        else:
            name = db.get_name_from_discriminator(
                ctx.author.name + ctx.author.discriminator
            )[0]
            queue = db.get_user_queue(name)
    except TypeError:
        return await ctx.send("User not registered.")

    await ctx.send(embed=handle_queue(queue, f"{name}' queue"))


@bot.command(name="pq", help="get priority queue")
async def priority_queue(ctx):
    queue = db.get_priority_queue()
    await ctx.send(embed=handle_queue(queue, "Priority queue"))


@bot.command(name="sr", help="search requests")
async def search_request_(ctx, *args):
    query = " ".join(args)
    requests = db.search_requests(query)

    if requests:
        message = await ctx.send("\n".join(requests))
        return [await message.add_reaction(emoji) for emoji in EMOJI_STRS]

    await ctx.send("apoco si pa")


def search_item(query, return_dict=False):
    if is_episode(query):
        EPISODE_LIST = db.get_list_of_episode_dicts()
        result = search_episode(EPISODE_LIST, query, raise_resting=False)
        if not return_dict:
            return f"{BASE}/episode/{result['id']}"
    else:
        MOVIE_LIST = db.get_list_of_movie_dicts()
        result = search_movie(MOVIE_LIST, query, raise_resting=False)
        if not return_dict:
            return f"{BASE}/movie/{result['tmdb']}"

    return result


@bot.command(name="search", help="search for a movie or an episode")
async def search(ctx, *args):
    query = " ".join(args)
    try:
        await ctx.send(search_item(query))
    except (MovieNotFound, EpisodeNotFound):
        await ctx.send("apoco si pa")


@bot.command(name="key", help="return a key value from a movie or an episode")
async def key(ctx, *args):
    key = args[0].strip()
    query = " ".join(args[1:])
    try:
        item = search_item(query, True)
        try:
            await ctx.send(f"{item['title']}'s {key}: {item[key]}")
        except KeyError:
            await ctx.send(f"Invalid key. Choose between: {', '.join(item.keys())}")

    except (MovieNotFound, EpisodeNotFound):
        await ctx.send("apoco si pa")


@bot.command(name="delete", help="delete a request by ID")
@commands.has_any_role("botmin", "verifier")
async def delete(ctx, arg):
    await ctx.send(db.remove_request(arg.strip()))


@bot.command(name="verify", help="verify a request by ID")
@commands.has_any_role("botmin", "verifier")
async def verify(ctx, arg):
    await ctx.send(db.verify_request(arg.strip()))


@bot.command(name="block", help="block an user by name")
@commands.has_any_role("botmin", "verifier")
async def block(ctx, *args):
    user = " ".join(args)
    db.block_user(user.strip())
    db.purge_user_requests(user.strip())
    await ctx.send("Ok.")


@bot.command(name="list", help="get user list (admin-only)")
@commands.has_permissions(administrator=True)
async def user_list(ctx, *args):
    users = db.get_discord_user_list()
    embed = Embed(title="List of users", description=", ".join(users))
    await ctx.send(embed=embed)


@bot.command(name="sql", help="run a sql command on Kinobot's DB (admin-only)")
@commands.has_permissions(administrator=True)
async def sql(ctx, *args):
    command = " ".join(args)
    try:
        db.execute_sql_command(command)
        message = f"Command OK: {command}."
    except sqlite3.Error as sql_exc:
        message = f"Error: {sql_exc}."

    await ctx.send(message)


@bot.command(name="purge", help="purge user requests by user (admin-only)")
@commands.has_permissions(administrator=True)
async def purge(ctx, user: User):
    try:
        user = db.get_name_from_discriminator(user.name + user.discriminator)[0]
    except TypeError:
        return await ctx.send("No requests found for given user")

    db.purge_user_requests(user)
    await ctx.send(f"Purged: {user}.")


@bot.event
async def on_message(message):
    try:
        embed_len = len(message.embeds[0].description)
    except IndexError:
        embed_len = 0

    if len(message.content) > 800 or embed_len > 800:
        channel = message.channel
        with open(MEME_IMG, "rb") as f:
            await channel.send(file=File(f))

    await bot.process_commands(message)


@bot.event
async def on_reaction_add(reaction, user):
    if user.bot:
        return

    if not str(reaction) in GOOD_BAD + EMOJI_STRS:
        return

    if not str(user.top_role) in "botmin verifier":
        return

    channel = bot.get_channel(reaction.message.channel.id)
    content = reaction.message.content

    if content.startswith("1. "):
        split_ = content.split("\n")
        try:
            index = split_[RANGE_DICT[str(reaction)]]
        except IndexError:
            return await channel.send("apoco si pa")

        request_id = index.split("-")[-1].strip()
        return await channel.send(db.verify_request(request_id))

    item_id = get_id_from_discord(content)

    if content.startswith("Added") and str(reaction) == GOOD_BAD[1]:
        return await channel.send(db.remove_request(item_id))

    if content.startswith("Possible NSFW") and str(reaction) == GOOD_BAD[0]:
        return await channel.send(db.verify_request(item_id))


@click.command("discord")
def discord_bot():
    " Run discord Bot. "
    logging.basicConfig(level=logging.INFO)
    bot.run(DISCORD_TOKEN)
