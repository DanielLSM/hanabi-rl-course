# hanabi-rl-course

This repository was made in the context of a DRL course. The purpose of the exercise was to read and use state-of-the-art DRL algorithms, such as Rainbow, to complex and cooperative games, such as Hanabi. 
The project is three fold:
- Train an agent within an Hanabi learning framework with a highly efficient (C++) and headless Hanabi implementation.
- Read and use an Hanabi webserver API in order to have human participants playing the game.
- Transform the gamestate of the highly efficient (C++) environment to be compatible with the webserver API, for the agent to operate in the same state space.

The agent was trained using a fork of a Rainbow implementation from [Hanabi Learning Environment](https://github.com/DanielLSM/hanabi-learning-environment). The webserver API used a fork of an [Hanabi live bot](https://github.com/sarahgillet/hanabi-live-bot), and several methods were implemented to transform the state space from the messages sent from the [Hanabi-live](https://hanabi.live/) webserver to be compatible with the state space from the learning framework, and vice-versa for the actions.

To test the code you need to do the following:
- Download the latest checkpoint of training: 
https://drive.google.com/file/d/1uzb18nvSMi6jTTm80avlIASbGxOx4KmM/view?usp=sharing
or
https://drive.google.com/drive/folders/1C6aWpyMDvx03usamvjz2_YU0MnFieDF9

- Execute the instructions bellow (tested on Ubuntu 16, 18 and 20 on python 3.6,3.7 and 3.8)

Video with the bellow installation instructions: https://www.youtube.com/watch?v=B5dL0C_ubwE

(Recommended) Create a simple conda environemnt with python=3.7
```
conda create -n hanabi-bot python=3.7
```

Install requirements with
```
pip install -r requirements.txt
```

Set up environment variables:
 ```
 cp .env_template .env
 [your favourite text editor] .env
 ```

Locate the checkpoints from training and run with:
```
python -um main \
  --base_dir=absolute_path_to_directory_containing_checkpoints_folder \
  --gin_files='configs/hanabi_rainbow.gin'
```
In a browser, log on to Hanabi Live and start a new table.
* In the pre-game chat window, send a private message to the bot in order to get it to join you, and include the password:
  * `/msg [username] /join [yourPassword]`
Then, start the game and play!
