
import discord
import random
import asyncio
import json
import os
from datetime import datetime, timedelta
import requests

# Server statistics tracking
server_stats = {
    'total_messages': 0,
    'commands_used': 0,
    'users_active_today': set()
}

# Fun facts database
fun_facts = [
    "A group of flamingos is called a 'flamboyance'! 🦩",
    "Honey never spoils! Archaeologists have found pots of honey in ancient Egyptian tombs that are over 3,000 years old! 🍯",
    "Bananas are berries, but strawberries aren't! 🍌🍓",
    "A shrimp's heart is in its head! 🦐",
    "The shortest war in history was between Britain and Zanzibar on August 27, 1896. It lasted only 38-45 minutes! ⚔️",
    "Dolphins have names for each other! 🐬",
    "A cloud can weigh more than a million pounds! ☁️",
    "Your stomach gets an entirely new lining every 3-4 days! 🫀",
    "The Great Wall of China isn't visible from space with the naked eye! 🏯",
    "Octopuses have three hearts and blue blood! 🐙"
]

# Quote database
inspirational_quotes = [
    "The only way to do great work is to love what you do. - Steve Jobs",
    "Life is what happens to you while you're busy making other plans. - John Lennon",
    "The future belongs to those who believe in the beauty of their dreams. - Eleanor Roosevelt",
    "It is during our darkest moments that we must focus to see the light. - Aristotle",
    "The only impossible journey is the one you never begin. - Tony Robbins",
    "In the midst of winter, I found there was, within me, an invincible summer. - Albert Camus",
    "Be yourself; everyone else is already taken. - Oscar Wilde",
    "Two things are infinite: the universe and human stupidity; and I'm not sure about the universe. - Albert Einstein",
    "You miss 100% of the shots you don't take. - Wayne Gretzky",
    "Whether you think you can or you think you can't, you're right. - Henry Ford"
]

# Joke database
jokes = [
    "Why don't scientists trust atoms? Because they make up everything! ⚛️",
    "Why did the scarecrow win an award? He was outstanding in his field! 🌾",
    "Why don't eggs tell jokes? They'd crack each other up! 🥚",
    "What do you call a fake noodle? An impasta! 🍝",
    "Why did the math book look so sad? Because it had too many problems! 📚",
    "What's the best thing about Switzerland? I don't know, but the flag is a big plus! 🇨🇭",
    "Why can't a bicycle stand up by itself? It's two tired! 🚲",
    "What do you call a bear with no teeth? A gummy bear! 🐻",
    "Why did the coffee file a police report? It got mugged! ☕",
    "What's orange and sounds like a parrot? A carrot! 🥕"
]

# Trivia questions database
trivia_questions = [
    {
        "question": "What is the capital of Australia?",
        "options": ["A) Sydney", "B) Melbourne", "C) Canberra", "D) Perth"],
        "answer": "C",
        "explanation": "Canberra is the capital of Australia, not Sydney as many people think!"
    },
    {
        "question": "Which planet is known as the Red Planet?",
        "options": ["A) Venus", "B) Mars", "C) Jupiter", "D) Saturn"],
        "answer": "B",
        "explanation": "Mars is called the Red Planet due to iron oxide (rust) on its surface!"
    },
    {
        "question": "What year did the Titanic sink?",
        "options": ["A) 1910", "B) 1911", "C) 1912", "D) 1913"],
        "answer": "C",
        "explanation": "The Titanic sank on April 15, 1912, after hitting an iceberg!"
    },
    {
        "question": "Which programming language was created by Guido van Rossum?",
        "options": ["A) Java", "B) Python", "C) C++", "D) JavaScript"],
        "answer": "B",
        "explanation": "Python was created by Guido van Rossum and first released in 1991!"
    },
    {
        "question": "What is the smallest prime number?",
        "options": ["A) 0", "B) 1", "C) 2", "D) 3"],
        "answer": "C",
        "explanation": "2 is the smallest and only even prime number!"
    }
]

# Active trivia sessions
active_trivia = {}

# User XP system
user_xp = {}
XP_FILE = "user_xp.json"

def load_user_xp():
    """Load user XP from file"""
    global user_xp
    try:
        if os.path.exists(XP_FILE):
            with open(XP_FILE, 'r') as f:
                user_xp = json.load(f)
        else:
            user_xp = {}
    except Exception as e:
        print(f"Error loading XP data: {e}")
        user_xp = {}

def save_user_xp():
    """Save user XP to file"""
    try:
        with open(XP_FILE, 'w') as f:
            json.dump(user_xp, f, indent=2)
    except Exception as e:
        print(f"Error saving XP data: {e}")

def add_xp(user_id, amount):
    """Add XP to a user"""
    user_id_str = str(user_id)
    if user_id_str not in user_xp:
        user_xp[user_id_str] = {"xp": 0, "level": 1}
    
    user_xp[user_id_str]["xp"] += amount
    
    # Calculate new level (every 100 XP = 1 level)
    new_level = (user_xp[user_id_str]["xp"] // 100) + 1
    old_level = user_xp[user_id_str]["level"]
    user_xp[user_id_str]["level"] = new_level
    
    save_user_xp()
    
    return new_level > old_level  # Return True if leveled up

def get_user_xp(user_id):
    """Get user's XP and level"""
    user_id_str = str(user_id)
    if user_id_str not in user_xp:
        return {"xp": 0, "level": 1}
    return user_xp[user_id_str]

async def handle_fun_fact_command(message):
    """Send a random fun fact"""
    fact = random.choice(fun_facts)
    
    embed = discord.Embed(
        title="🧠 Fun Fact!",
        description=fact,
        color=discord.Color.blue()
    )
    embed.set_footer(text="Did you know? 🤔")
    
    await message.channel.send(embed=embed)
    
    # Add XP for using commands
    leveled_up = add_xp(message.author.id, 5)
    if leveled_up:
        user_data = get_user_xp(message.author.id)
        await message.channel.send(f"🎉 {message.author.mention} leveled up to level {user_data['level']}!")

async def handle_quote_command(message):
    """Send an inspirational quote"""
    quote = random.choice(inspirational_quotes)
    
    embed = discord.Embed(
        title="💭 Inspirational Quote",
        description=f"*\"{quote}\"*",
        color=discord.Color.gold()
    )
    embed.set_footer(text="Stay motivated! ✨")
    
    await message.channel.send(embed=embed)
    
    # Add XP for using commands
    leveled_up = add_xp(message.author.id, 5)
    if leveled_up:
        user_data = get_user_xp(message.author.id)
        await message.channel.send(f"🎉 {message.author.mention} leveled up to level {user_data['level']}!")

async def handle_joke_command(message):
    """Send a random joke"""
    joke = random.choice(jokes)
    
    embed = discord.Embed(
        title="😂 Here's a joke for you!",
        description=joke,
        color=discord.Color.green()
    )
    embed.set_footer(text="Hope that made you smile! 😄")
    
    await message.channel.send(embed=embed)
    
    # Add XP for using commands
    leveled_up = add_xp(message.author.id, 5)
    if leveled_up:
        user_data = get_user_xp(message.author.id)
        await message.channel.send(f"🎉 {message.author.mention} leveled up to level {user_data['level']}!")

async def handle_trivia_command(message):
    """Start a trivia question"""
    if message.channel.id in active_trivia:
        await message.channel.send("🧩 There's already an active trivia question in this channel! Answer it first.")
        return
    
    question_data = random.choice(trivia_questions)
    
    embed = discord.Embed(
        title="🧩 Trivia Time!",
        description=f"**{question_data['question']}**\n\n" + "\n".join(question_data['options']),
        color=discord.Color.purple()
    )
    embed.set_footer(text="Reply with A, B, C, or D! ⏰ You have 30 seconds!")
    
    trivia_msg = await message.channel.send(embed=embed)
    
    # Store the trivia data
    active_trivia[message.channel.id] = {
        "answer": question_data['answer'],
        "explanation": question_data['explanation'],
        "start_time": datetime.now(),
        "message_id": trivia_msg.id
    }
    
    # Auto-timeout after 30 seconds
    await asyncio.sleep(30)
    
    if message.channel.id in active_trivia:
        embed = discord.Embed(
            title="⏰ Time's Up!",
            description=f"The correct answer was **{question_data['answer']}**!\n\n{question_data['explanation']}",
            color=discord.Color.red()
        )
        await message.channel.send(embed=embed)
        del active_trivia[message.channel.id]

async def handle_trivia_answer(message):
    """Handle trivia answers"""
    if message.channel.id not in active_trivia:
        return False
    
    user_answer = message.content.upper().strip()
    if user_answer not in ['A', 'B', 'C', 'D']:
        return False
    
    trivia_data = active_trivia[message.channel.id]
    correct_answer = trivia_data['answer']
    explanation = trivia_data['explanation']
    
    # Calculate response time
    response_time = (datetime.now() - trivia_data['start_time']).total_seconds()
    
    if user_answer == correct_answer:
        # Correct answer
        xp_reward = max(10, int(20 - response_time))  # Faster answers get more XP
        leveled_up = add_xp(message.author.id, xp_reward)
        
        embed = discord.Embed(
            title="🎉 Correct!",
            description=f"**{message.author.display_name}** got it right!\n\n{explanation}\n\n**XP Reward:** +{xp_reward} XP",
            color=discord.Color.green()
        )
        
        if leveled_up:
            user_data = get_user_xp(message.author.id)
            embed.add_field(name="🆙 Level Up!", value=f"Congratulations! You're now level {user_data['level']}!", inline=False)
        
    else:
        # Incorrect answer
        embed = discord.Embed(
            title="❌ Incorrect!",
            description=f"The correct answer was **{correct_answer}**.\n\n{explanation}",
            color=discord.Color.red()
        )
    
    embed.set_footer(text=f"Response time: {response_time:.1f} seconds")
    await message.channel.send(embed=embed)
    
    # Remove the trivia question
    del active_trivia[message.channel.id]
    return True

async def handle_xp_command(message, target_user=None):
    """Show user's XP and level"""
    if target_user:
        user = target_user
        user_data = get_user_xp(user.id)
        title = f"📊 {user.display_name}'s Stats"
    else:
        user = message.author
        user_data = get_user_xp(user.id)
        title = "📊 Your Stats"
    
    xp_to_next_level = 100 - (user_data['xp'] % 100)
    
    embed = discord.Embed(
        title=title,
        color=discord.Color.blue()
    )
    embed.add_field(name="🎖️ Level", value=user_data['level'], inline=True)
    embed.add_field(name="⭐ Total XP", value=user_data['xp'], inline=True)
    embed.add_field(name="📈 XP to Next Level", value=xp_to_next_level, inline=True)
    
    embed.set_thumbnail(url=user.avatar.url if user.avatar else user.default_avatar.url)
    
    await message.channel.send(embed=embed)

async def handle_leaderboard_command(message):
    """Show XP leaderboard"""
    if not user_xp:
        await message.channel.send("📊 No one has earned XP yet! Use commands to start earning!")
        return
    
    # Sort users by XP
    sorted_users = sorted(user_xp.items(), key=lambda x: x[1]['xp'], reverse=True)
    
    embed = discord.Embed(
        title="🏆 XP Leaderboard",
        description="Top users by experience points!",
        color=discord.Color.gold()
    )
    
    for i, (user_id, data) in enumerate(sorted_users[:10], 1):
        try:
            user = message.guild.get_member(int(user_id))
            if user:
                medal = "🥇" if i == 1 else "🥈" if i == 2 else "🥉" if i == 3 else f"{i}."
                embed.add_field(
                    name=f"{medal} {user.display_name}",
                    value=f"Level {data['level']} • {data['xp']} XP",
                    inline=False
                )
        except:
            continue
    
    await message.channel.send(embed=embed)

async def handle_server_stats_command(message):
    """Show server statistics"""
    guild = message.guild
    
    # Count online members
    online_members = sum(1 for member in guild.members if member.status != discord.Status.offline)
    
    # Count different channel types
    text_channels = len(guild.text_channels)
    voice_channels = len(guild.voice_channels)
    
    embed = discord.Embed(
        title=f"📊 {guild.name} Statistics",
        color=discord.Color.blue()
    )
    
    embed.add_field(name="👥 Total Members", value=guild.member_count, inline=True)
    embed.add_field(name="🟢 Online Members", value=online_members, inline=True)
    embed.add_field(name="🤖 Bots", value=sum(1 for member in guild.members if member.bot), inline=True)
    
    embed.add_field(name="💬 Text Channels", value=text_channels, inline=True)
    embed.add_field(name="🔊 Voice Channels", value=voice_channels, inline=True)
    embed.add_field(name="🎭 Roles", value=len(guild.roles), inline=True)
    
    embed.add_field(name="📅 Server Created", value=guild.created_at.strftime("%B %d, %Y"), inline=True)
    embed.add_field(name="👑 Owner", value=guild.owner.mention if guild.owner else "Unknown", inline=True)
    embed.add_field(name="🆔 Server ID", value=guild.id, inline=True)
    
    if guild.icon:
        embed.set_thumbnail(url=guild.icon.url)
    
    await message.channel.send(embed=embed)

async def handle_user_info_command(message, target_user=None):
    """Show user information"""
    user = target_user if target_user else message.author
    
    embed = discord.Embed(
        title=f"👤 {user.display_name}",
        color=user.color if user.color != discord.Color.default() else discord.Color.blue()
    )
    
    embed.add_field(name="📛 Username", value=f"{user.name}#{user.discriminator}", inline=True)
    embed.add_field(name="🆔 User ID", value=user.id, inline=True)
    embed.add_field(name="🤖 Bot", value="Yes" if user.bot else "No", inline=True)
    
    embed.add_field(name="📅 Account Created", value=user.created_at.strftime("%B %d, %Y"), inline=True)
    
    if isinstance(user, discord.Member):
        embed.add_field(name="📅 Joined Server", value=user.joined_at.strftime("%B %d, %Y") if user.joined_at else "Unknown", inline=True)
        embed.add_field(name="🔝 Highest Role", value=user.top_role.mention, inline=True)
        
        # Show user's roles (excluding @everyone)
        roles = [role.mention for role in user.roles if role.name != "@everyone"]
        if roles:
            embed.add_field(name="🎭 Roles", value=" ".join(roles[:10]), inline=False)
    
    embed.set_thumbnail(url=user.avatar.url if user.avatar else user.default_avatar.url)
    
    await message.channel.send(embed=embed)

async def handle_coin_flip_command(message):
    """Flip a coin"""
    result = random.choice(["Heads", "Tails"])
    emoji = "🪙" if result == "Heads" else "🔄"
    
    embed = discord.Embed(
        title="🪙 Coin Flip",
        description=f"**{result}!** {emoji}",
        color=discord.Color.gold()
    )
    
    await message.channel.send(embed=embed)
    
    # Add XP for using commands
    leveled_up = add_xp(message.author.id, 2)
    if leveled_up:
        user_data = get_user_xp(message.author.id)
        await message.channel.send(f"🎉 {message.author.mention} leveled up to level {user_data['level']}!")

async def handle_dice_roll_command(message, sides=6):
    """Roll a dice"""
    if sides < 2 or sides > 100:
        await message.channel.send("🎲 Please choose between 2 and 100 sides!")
        return
    
    result = random.randint(1, sides)
    
    embed = discord.Embed(
        title=f"🎲 Dice Roll (d{sides})",
        description=f"**You rolled: {result}**",
        color=discord.Color.red()
    )
    
    await message.channel.send(embed=embed)
    
    # Add XP for using commands
    leveled_up = add_xp(message.author.id, 2)
    if leveled_up:
        user_data = get_user_xp(message.author.id)
        await message.channel.send(f"🎉 {message.author.mention} leveled up to level {user_data['level']}!")

async def handle_poll_command(message, content):
    """Create a simple yes/no poll"""
    poll_question = content.strip()
    
    if not poll_question:
        await message.channel.send("📊 Please provide a question for the poll! Example: `poll Should we have pizza tonight?`")
        return
    
    embed = discord.Embed(
        title="📊 Poll",
        description=poll_question,
        color=discord.Color.blue()
    )
    embed.add_field(name="How to vote:", value="React with ✅ for Yes or ❌ for No", inline=False)
    embed.set_footer(text=f"Poll created by {message.author.display_name}")
    
    poll_msg = await message.channel.send(embed=embed)
    await poll_msg.add_reaction("✅")
    await poll_msg.add_reaction("❌")
    
    # Add XP for creating polls
    leveled_up = add_xp(message.author.id, 10)
    if leveled_up:
        user_data = get_user_xp(message.author.id)
        await message.channel.send(f"🎉 {message.author.mention} leveled up to level {user_data['level']}!")

# Initialize XP system
load_user_xp()
