import json
import telebot
import os
from pprint import pprint
from scholarly import scholarly
from sqlitedict import SqliteDict


def main():
    os.makedirs('./data', exist_ok=True)

    db = SqliteDict('./data/db.sqlite', autocommit=True)

    config = json.load(open('./conf.json'))
    bot = telebot.TeleBot(token=config['token'], parse_mode="html")
    bot.send_message(chat_id=config['chat_id'], text="Checking for new citations..")

    search_query = scholarly.search_author(config["author_name"])
    first_author_result = next(search_query)

    author = scholarly.fill(first_author_result)
    tot_author_citation = author['citedby']
    publications = author['publications']

    print(f"Total citation: {tot_author_citation}")
    for publication in publications:
        pub_id = publication['author_pub_id']
        pub_title = publication['bib']['title']
        pub_citations = publication['num_citations']
        pub_year = publication['bib']['pub_year'] if 'pub_year' in publication['bib'] else 'N/A'
        print(f"ID: {pub_id}, Title: {pub_title}, Citations: {pub_citations}, Year: {pub_year}")

        if pub_id not in db:
            db[pub_id] = {
                'title': pub_title,
                'citations': pub_citations,
                'year': pub_year
            }
            
            bot.send_message(chat_id=config['chat_id'], 
                             text=f"<b>New publication:</b> {pub_title} ({pub_year})\n"
                                  f"<b>Citations:</b> {pub_citations}")
            
        else:
            old_citations = db[pub_id]['citations']
            if old_citations != pub_citations:
                db[pub_id]['citations'] = pub_citations
                bot.send_message(chat_id=config['chat_id'], 
                                 text=f"New citations ({pub_citations - old_citations}, tot {pub_citations}) for: <i>{pub_title}</i> ({pub_year})\n")
    
    db.close()


if __name__ == '__main__':
    main()
    

    