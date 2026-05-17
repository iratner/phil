# Phil Game Rules

## The Board
1. The board consists of 2 levels of blocks
2. The bottom level of blocks is composed of holes and solid blocks
3. The top level of blocks is composed of various blocks that can be moved, and some that cannot be moved
4. All blocks have properties that produce interactions with other blocks on the same level, other blocks on the level below, or other blocks on the level above them
5. The board is at most 16 columns by 24 rows (this may change later)
6. Both levels should most likely use a 2d array
7. The first level should only be made of empty spaces, [Immovable Blocks](#immovable-iron) and [Ice Blocks](#ice)

## Phil (The main character)
1. Phil is a little spherical fellow that needs to reach a glowing sphere on the board.
2. Phil hangs out on the second level
3. Phil can only step on the bottom level blocks that are not holes, and do not have a property that prevents Phil from stepping on them
4. Phil cannot jump over blocks on the same level as him (the second level)
5. Phil doesn't move during the course of the game.  He waits for a path to be created

## Gameplay
1. The player moves the top level blocks to create a path for Phil
2. The path needs to reach a __GOAL__: A glowing sphere 
3. each time a block is interacted with, and it reaches it's final destination, the game board is updated by visually displaying all the blocks Phil can reach
4. The player moves the blocks with either a touch interaction, or a mouse interaction.  A touch would be a slide in the direction the block needs to move.  A mouse would be a click on the block, and click on the direction, or a mouse down and slide similar to the touch interaction
5. Each time the player makes a move they receive points for that move
6. __WIN CONDITION__ when a path is available for Phil to travel across to reach the __GOAL__, the level has been completed
  
### Move Types
1. regular move - 50 points
2. special move - 100 points
3. move that fills a hole - 300 points

Moves of type 1 and 2 are mutually exclusive.  A move of type 3 is additive.  

### The Bonus Multiplier Time Bar

At the top of the game screen there is a shrinking time bar that takes 5 seconds to go down to zero.  It resets as soon as a the player completes another move, but before the block reaches it's final destination.  Each time the player makes a move before the time runs out, a multiplier is added to the player's game state.  Multipliers are cumulative.  The add x2 each consecutive time the move is made before the time runs out.  Each time a player makes a move, the multiplier is used to increase the score for that move.  The first time a move is not made before the multiplier time bar runs out, the multiplier resets to x1

### Block Types

#### Property Defintions
1. immovable - nothing can move this block
2. player non-movable - player cannot move this block, but game intreactions might

#### Blocks

##### Immovable (iron) 
* blocks that cannot be moved
   
##### Stone
* blocks that move exactly on space
  
##### Ice 
* blocks that move one space
* When they fall into a hole on the first level, other blocks that are moved onto them keep sliding in the same direction

##### Bumper 
* stationary blocks.  
* When a block is moved into a cell that is adjacent to them, if another block sits on the opposite side, and on same travel axis, that block gets bumped into the next cell

##### Spike  
* a spiked block that cannot be move by the game player directly
 
