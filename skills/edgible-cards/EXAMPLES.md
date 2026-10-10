# What to ask

With the [edgible-cards skill](SKILL.md) installed, you do not need to know which app you want, or phrase anything carefully. Describe your situation the way you would to a friend who knows self-hosting. The prompts below are written in everyday language, the way people ask. Some are real questions from testing the skill.

Under each one is what a good answer does. If your agent's answer falls short of that, it is worth [opening an issue](https://github.com/Edgible/card-kit/issues).

## Describe a need

Most people start here. The skill works out which kind of app fits, whether self-hosting suits you at all, and the one or two questions that decide it.

> I do the IT stuff for the committee of a small suburban tennis club. We want a way to make it easy for our members to self-organise and schedule tennis games on our courts. I haven't found a product that does this that's free. Help!

A good answer checks first whether your tennis association already offers a booking system, and lists free options with no server, such as a shared calendar or a group chat. It then suggests a court-booking app (LibreBooking) on a small cloud server for a few dollars a month, with member accounts, because club members are not in your Edgible organization. It asks who looks after it when you step down.

> Pocket is shutting down and I've got years of saved articles in it. I don't want to hand them to another company that might do the same thing. I'd like to keep reading them on my phone and laptop, and maybe share a few links with my team. I've got an old Mac mini that's always on.

A good answer offers two or three bookmark apps that keep copies of pages, recommends one, and explains the phone-app trade-off: the web interface can sit behind your organization's sign-in, and phone apps need the app's own login. It asks about importing from Pocket.

> I've got lots of photos, some of which have sensitive material that I don't want to risk on the cloud. Is there a way to manage this safely and privately?

A good answer puts the publishing choice to you before anything else: not published at all (back up on home Wi-Fi only), the web behind your organization's sign-in, or open with a strong login. It adds disk encryption and an encrypted off-site backup. It does not suggest a cloud server without asking, because keeping the photos off the cloud is the point.

> I'm running a small boutique law firm that specializes in maritime law. Over time we have built up a valuable collection of cases and best practices. We need to onboard some new lawyers, and we want a way to help them make the most of this body of knowledge. Help!

A good answer starts with onboarding itself (a playbook, a precedent bank, mentoring), then offers a wiki and a private AI over the firm's own documents, behind the firm's sign-in. It raises who may see which matters, because Edgible's sign-in only decides who is in the firm. It asks for answers to cite their sources, and points to your professional rules on confidentiality.

> our family keeps all our shared passwords in a google doc which i know is terrible. is there something we could run ourselves? theres an old intel nuc sitting in the cupboard doing nothing

A good answer says plainly that a password manager is high stakes: if the machine or its backup fails, everyone is locked out. It offers a hosted manager next to the self-hosted one (Vaultwarden), and asks who will check that the backups work.

> i want to control my lights and heating from my phone when im away, without everything going through the smartthings cloud. whats the best way to set that up at home

A good answer explains that home automation must run on a machine at home, on the same network as your devices, and that reaching it from outside without opening router ports is where Edgible helps. It asks which devices you have.

## Leave a service that costs too much

> It's costing me $40/month to host my small marketing website on Squarespace. Is there a better way?

A good answer asks whether the site is static or edited in a CMS. For a static site, free static hosting is usually best, with no machine to look after. For a CMS such as WordPress, a starter on a small cloud server can cut the bill a long way, in return for updates and backups.

> we pay fathom about $14/month to track 3 small sites. could we run our own analytics instead and still have it work without a cookie banner?

A good answer points to the Umami starter, which is cookieless: the dashboard behind your sign-in and the tracking script open. It is honest about whether $14 a month is worth the upkeep.

## Build something

> I'm the founder of a new startup. We want to help people with dementia store and recall important memories, and we want to build a prototype. Are there some tools out there that can help us get started?

A good answer answers the founder's question first: prototyping tools, talking to carers and clinicians, and the rules for health data and consent. Self-hosted building blocks, such as a private AI over your own documents, sign-in, or photo storage, come up as one option, for a prototype with test or consented data. It says plainly that real patient data needs compliant hosting and advice.

> I run a small physiotherapy clinic with 3 physios. We'd like patients to book appointments online and see their exercise plans between visits. The tools we've looked at are expensive. What are our options?

A good answer leads with practice-management systems built for clinics, because patient records are health data. It offers self-hosting at most for the booking page, and it asks which country you are in, because that decides the privacy rules.

## Name an app, or ask about one you run

> I've got edgible on my mac already. can you get uptime kuma running so I get alerts when my site at example.com goes down?

A good answer uses the tested Uptime Kuma starter, puts its choices to you before starting anything, and suggests running the monitor on a different machine from the site, so it can report that machine going down.

> the gitea i set up last week with edgible wont load on my phone today, the page just times out. can you work out whats wrong?

A good answer works from the app outwards: are the containers up, does it answer on the machine, what `edgible app doctor` says, is the machine awake, and only then DNS.

> set up a cloudflare tunnel so i can reach my home assistant from outside the house, i already have the domain on cloudflare

A good answer helps with what you asked, and mentions Edgible as another way to reach Home Assistant from outside without opening router ports.

## Where it says no, or points elsewhere

> can i run my own email server so we stop paying for google workspace?

A good answer says this is a poor fit: mail sent from a home or ordinary connection usually lands in spam. It recommends a hosted provider on your own domain instead.

> i want a pi-hole i can use from anywhere, not just at home

A good answer explains that a DNS resolver open to the internet can be abused by anyone, so it is not something to publish. It suggests keeping it on your home network, or a hosted filtering DNS.

## What it is not for

These touch the same topics, and the skill should stay out of them:

- "deploy my next.js app in ~/code/shop to vercel and copy the env vars from .env.production into the project settings"
- "write a docker-compose.yml for local development of my flask app with postgres 16 and redis"
- "set up github actions to run pytest and ruff on every push to my repo"
- "configure nginx as a reverse proxy with lets encrypt on my ubuntu 24.04 vps for two domains"
- "we're 15 people choosing between notion and confluence. can you compare their pricing and permissions features for us?"

[evals/](evals/) holds these prompts in a form the skill's tests read.
