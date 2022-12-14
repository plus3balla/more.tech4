# -*- coding: utf-8 -*-
import copy
import os
import re
from collections import Counter
from datetime import datetime
from itertools import chain, product, combinations
from statistics import median
from typing import List

import gensim.models
import numpy as np
import pandas as pd
import spacy
from sklearn.cluster import KMeans
from sklearn.feature_extraction.text import TfidfVectorizer
from sumy.nlp.tokenizers import Tokenizer
from sumy.parsers.plaintext import PlaintextParser
from sumy.summarizers.lex_rank import LexRankSummarizer
from wordcloud import WordCloud
from PIL import Image

POS_TAGS = ['NOUN', 'ADJ', 'VERB', 'ADV', 'PROPN']
NLP = spacy.load('ru_core_news_lg')
LRS = LexRankSummarizer()


def lemmatize(article: str) -> List[str]:
    """
    Removes links, e-mails and lemmatize the article.
    Used in eval_data_4_role()

    :param article: String containing the full article
    :return: List of tokenized articles
    """
    # remove e-mails and url links
    article = re.sub(r'\S*@\S*\s?', '', article)
    article = re.sub(r'http\S+', '', article)
    article = re.sub(r'www.\S+', '', article)

    # remove all non-alphabetic characters
    article = re.sub('[^а-яА-Я]+', ' ', article)

    doc = NLP(article)
    article = [token.lemma_ for token in doc if token.pos_ in POS_TAGS]

    return article


def remove_similar(dataframe: pd.DataFrame) -> pd.DataFrame:
    """
    If the dataframe contains articles that are very similar in meaning,
    removes the one with the longer digest.
    Used in eval_data_4_role()

    :param dataframe: Full dataframe received from the bot
    :return The same dataframe, but now without implicitly similar articles
    """
    temp_series = copy.deepcopy(dataframe["Digest"])
    temp_series = temp_series.map(lambda x: NLP(" ".join(x)))

    digest_pairs = list(combinations(temp_series, r=2))
    for digest1, digest2 in digest_pairs:
        if digest1.similarity(digest2) >= 0.87:
            # keep the article with the shorter digest; nobody has
            # the time to read these days
            candidate = digest1 if len(digest1) > len(digest2) else digest2
            # dataframe = dataframe[dataframe["Digest"] != candidate]
            try:
                dataframe = dataframe.drop(
                    temp_series.index[temp_series == candidate])
            except KeyError:
                continue

    return dataframe


def form_ngrams(articles: pd.Series) -> pd.Series:
    """
    Substitutes collocations with respective n-grams where it can be applied.
    Used in eval_data_4_role()

    :param articles: Series containing the necessary tokenized articles
    :return: Series with n-grams added
    """
    bigram = gensim.models.Phrases(articles)
    trigram = gensim.models.Phrases(bigram[articles])

    bigram_mod = gensim.models.phrases.Phraser(bigram)
    trigram_mod = gensim.models.phrases.Phraser(trigram)

    temp = pd.Series(0, index=np.arange(len(articles)))
    for i, entry in articles.items():
        temp[i] = bigram_mod[entry]
        temp[i] = trigram_mod[bigram_mod[entry]]

    return temp


def tf_idf_nitems(article: List[str], n=10) -> List[str]:
    """
    Applies TF-IDF to a tokenized article. Used in eval_data_4_role()

    :param article: Tokenized article
    :param n: No. of articles the function should return
    :return: List of n most frequent terms
    """
    # get n most important words in the article
    tf_idf_vectorizer = TfidfVectorizer(use_idf=True)
    tf_idf = tf_idf_vectorizer.fit_transform(article)
    results = pd.DataFrame(tf_idf[0].T.todense(
    ), index=tf_idf_vectorizer.get_feature_names_out(), columns=['TF-IDF'])
    results = results.sort_values('TF-IDF', ascending=False)
    return results.head(n).index.to_list()


def digest(article: str, n=3) -> List[str]:
    """
    Forms a digest based on the article given. Used in eval_data_4_role()

    :param article: String containing the full article
    :param n: No. of sentences to return
    :return: List of n sentences that summarize the article
    """
    # TODO: заменить токенизатором spaCy, если останется время:
    my_parser = PlaintextParser.from_string(article, Tokenizer('russian'))
    #
    lexrank_summary = LRS(
        my_parser.document, sentences_count=n)
    digest_sentences = []
    for sentence in lexrank_summary:
        digest_sentences.append(str(sentence))
    return digest_sentences


def eval_article(terms: List[str], role_keywords: List[str]) -> float:
    """
    Evaluate the given article based on the similarity with the keywords
    for a role. Used in eval_data_4_role()

    :param terms: Most frequent terms of the article for analysis (use TF-IDF)
    :param role_keywords: List of keywords
    :return: Mean value for the article
    """

    results = []
    terms = list(map(NLP, terms))
    role_keywords = list(map(NLP, role_keywords))

    for article_word, keyword in product(terms, role_keywords):
        results.append(article_word.similarity(keyword))

    return median(results)


def generate_trend_wordcloud(articles: pd.Series) -> None:
    """
    Splits the dataframe (should be already lemmatized, etc.) in half, 
    tries to find trending keywords,
    generates a WordCloud image at imgs/word_clouds/

    :param articles: Series of tokenized articles from a dataframe
    """

    if len(articles) < 20:
        raise ValueError(
            'Given Series is too short to meaningfully find trends')

    # divide Series in two
    half_point = int(len(articles) / 2)
    old_articles = articles.head(half_point)
    new_articles = articles.tail(half_point - half_point % 2)

    old_articles_counted = Counter(list(chain.from_iterable(old_articles)))
    new_articles_counted = Counter(list(chain.from_iterable(new_articles)))

    # get the difference between two dictionaries
    new_articles_counted.subtract(old_articles_counted)
    # .most_common() sorts the diff dict
    difference = dict(new_articles_counted.most_common())

    # use k-means to divide the dictionary of keyword popularity difference into 3 clusters
    y_pred = KMeans(n_clusters=3).fit_predict(
        np.asarray(list(difference.values())).reshape(-1, 1))

    # map the variable to corresponding cluster
    trending_keywords = dict()
    for i in range(1, len(y_pred)):
        if y_pred[i] != y_pred[i - 1]:
            trending_keywords = dict(list(difference.items())[0:i])
            break

    vtb_mask = np.array(Image.open('imgs/vtb_logo.png'))
    color_function = lambda *args, **kwargs: "hsl(230,100%%, %d%%)" \
        % np.random.randint(20, 60)

    wordcloud = WordCloud(background_color='white', mask=vtb_mask,
                          color_func=color_function).generate_from_frequencies(
        frequencies=trending_keywords)
    if not os.path.exists('imgs/word_clouds'):
        os.makedirs('imgs/word_clouds')

    wordcloud.to_file(f'imgs/word_clouds/{datetime.now():%Y-%m-%d-%H%M%S}.jpg')

# if __name__ == '__main__':
#     generate_trend_wordcloud(df['Text'])
