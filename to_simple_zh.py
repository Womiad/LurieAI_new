
from opencc import OpenCC
import re

def to_simple_zh(text):

    text = text.replace("~","，波浪符，")

    cc = OpenCC('tw2s')
    # Define a regex pattern to match all punctuation except ，。！
    pattern = r'[^\w\s，。！《》「」]'
    # Replace all matched punctuation with ，
    replaced_text = re.sub(pattern, '，', text)
    pattern = r'，+'
    # Replace multiple consecutive ， with a single ，
    cleaned_text = re.sub(pattern, '，', replaced_text)
    print(cleaned_text)
    
    return cc.convert(cleaned_text)

if __name__ == "__main__":
    to_simple_zh("你說得對，但是《原神》是由米哈遊自主研發的一款全新開放世界冒險遊戲。遊戲發生在一個被稱作「提瓦特」的幻想世界，在這裡，被神選中的人將被授予「神之眼」，導引元素之力。你將扮演一位名為「旅行者」的神秘角色，在自由的旅行中邂逅性格各異、能力獨特的同伴們，和他們一起擊敗強敵，找回失散的親人——同時，逐步發掘「原神」的真相。")
