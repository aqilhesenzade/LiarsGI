"""
ds.py -- the four hand-made data structures this project is built on.

    LinkedList  (syllabus week 3)  ->  a player's hand of cards
    Stack       (syllabus week 4)  ->  the pile of face-down plays on the table
    MaxHeap     (syllabus week 8)  ->  the bot's priority queue of candidate moves
    CircularQueue (weeks 2 + 4)    ->  the bot's sliding-window memory of how the opponent reacts

Nothing here uses `collections`, `heapq` or `queue`: everything is written from scratch
so every line can be explained (and its complexity counted) during the presentation.

Complexity notation: n = number of items currently stored in the structure.
"""


# ==========================================================================
# 1. LINKED LIST  (singly linked, kept sorted)
# ==========================================================================
class Node:
    """One cell of a singly linked list: a value plus a pointer to the next cell."""

    __slots__ = ("value", "next")

    def __init__(self, value, nxt=None):
        """Create a node.

        Time:  O(1)
        Space: O(1)
        """
        self.value = value
        self.next = nxt


class LinkedList:
    """Singly linked list used as a player's hand (cards are kept sorted by colour).

    Why a linked list for a hand?  Cards are constantly removed from the *middle*
    (you play a green card from between reds and blues).  A linked list does that by
    re-pointing one pointer, with no shifting of the other cards like an array would need.
    Downside: no random access -- to reach the k-th card we must walk k nodes.
    """

    def __init__(self):
        """Create an empty list.

        Time:  O(1)
        Space: O(1)
        """
        self.head = None
        self._size = 0

    def __len__(self):
        """Number of stored values (kept in a counter, so no walk is needed).

        Time:  O(1)
        Space: O(1)
        """
        return self._size

    def is_empty(self):
        """True when the list has no nodes.

        Time:  O(1)
        Space: O(1)
        """
        return self.head is None

    def __iter__(self):
        """Walk the list from head to tail, yielding values one by one.

        Time:  O(n) for a full walk
        Space: O(1)
        """
        cur = self.head
        while cur is not None:
            yield cur.value
            cur = cur.next

    def insert_sorted(self, value):
        """Insert `value` so that the list stays in ascending order.

        Three cases: empty list / new smallest value (new head) / somewhere after the head.

        Time:  O(n)  (walk until the right position)
        Space: O(1)  (one new node)
        """
        node = Node(value)
        if self.head is None or value < self.head.value:
            node.next = self.head
            self.head = node
        else:
            cur = self.head
            while cur.next is not None and cur.next.value <= value:
                cur = cur.next
            node.next = cur.next
            cur.next = node
        self._size += 1

    def remove_first(self, value):
        """Delete the first node holding `value`; return True if something was removed.

        Time:  O(n)  (worst case: value is last or missing)
        Space: O(1)
        """
        prev, cur = None, self.head
        while cur is not None:
            if cur.value == value:
                if prev is None:
                    self.head = cur.next          # deleting the head
                else:
                    prev.next = cur.next          # bypass the node
                self._size -= 1
                return True
            prev, cur = cur, cur.next
        return False

    def clear(self):
        """Drop every node (Python's garbage collector frees them).

        Time:  O(1)
        Space: O(1)
        """
        self.head = None
        self._size = 0

    def to_list(self):
        """Copy the values into a normal Python list (handy for printing).

        Time:  O(n)
        Space: O(n)
        """
        return list(self)


# ==========================================================================
# 2. STACK  (array based, LIFO)
# ==========================================================================
class Stack:
    """LIFO stack backed by a dynamic array (Python list).

    The table pile is a stack because a call only ever inspects the *most recent* play:
    last placed = first revealed.  Linked list = node based, stack = array based:
    two different ways to store a sequence, side by side in one project.
    """

    def __init__(self):
        """Create an empty stack.

        Time:  O(1)
        Space: O(1)
        """
        self._items = []

    def __len__(self):
        """Number of items on the stack.

        Time:  O(1)
        Space: O(1)
        """
        return len(self._items)

    def is_empty(self):
        """True when nothing is stacked.

        Time:  O(1)
        Space: O(1)
        """
        return not self._items

    def push(self, item):
        """Put `item` on top.

        Time:  O(1) amortised (the array occasionally doubles its capacity)
        Space: O(1)
        """
        self._items.append(item)

    def pop(self):
        """Remove and return the top item; IndexError if empty.

        Time:  O(1)
        Space: O(1)
        """
        if not self._items:
            raise IndexError("pop from empty stack")
        return self._items.pop()

    def peek(self):
        """Return the top item without removing it; IndexError if empty.

        Time:  O(1)
        Space: O(1)
        """
        if not self._items:
            raise IndexError("peek at empty stack")
        return self._items[-1]

    def clear(self):
        """Remove everything.

        Time:  O(1)
        Space: O(1)
        """
        self._items = []

    def to_list(self):
        """Bottom-to-top copy of the items (for tests and debugging).

        Time:  O(n)
        Space: O(n)
        """
        return list(self._items)


# ==========================================================================
# 3. MAX-HEAP  (array based binary heap = priority queue)
# ==========================================================================
class MaxHeap:
    """Binary max-heap stored in an array: children of index i are 2i+1 and 2i+2.

    The bot scores every legal move and puts them in this heap, so the best
    move is always at the root.  `key(item)` says how items are compared.
    """

    def __init__(self, key=lambda x: x):
        """Create an empty heap ordered by `key(item)` (largest key = root).

        Time:  O(1)
        Space: O(1)
        """
        self._a = []
        self._key = key

    def __len__(self):
        """Number of items in the heap.

        Time:  O(1)
        Space: O(1)
        """
        return len(self._a)

    def is_empty(self):
        """True when the heap holds nothing.

        Time:  O(1)
        Space: O(1)
        """
        return not self._a

    def peek(self):
        """Look at the best item without removing it; IndexError if empty.

        Time:  O(1)
        Space: O(1)
        """
        if not self._a:
            raise IndexError("peek at empty heap")
        return self._a[0]

    def push(self, item):
        """Insert an item: append at the end, then sift it UP to its place.

        Time:  O(log n)
        Space: O(1)
        """
        self._a.append(item)
        self._sift_up(len(self._a) - 1)

    def pop(self):
        """Remove and return the best item: move the last item to the root, sift it DOWN.

        Time:  O(log n)
        Space: O(1)
        """
        if not self._a:
            raise IndexError("pop from empty heap")
        a = self._a
        a[0], a[-1] = a[-1], a[0]
        best = a.pop()
        if a:
            self._sift_down(0)
        return best

    def heapify(self, items):
        """Build a heap from an unsorted iterable (Floyd's bottom-up construction).

        Sifting down from the last parent to the root is O(n) in total -- cheaper
        than n separate pushes, which would cost O(n log n).

        Time:  O(n)
        Space: O(n)  (the internal array)
        """
        self._a = list(items)
        for i in range(len(self._a) // 2 - 1, -1, -1):
            self._sift_down(i)

    def to_list(self):
        """Copy of the backing array in heap order (index 0 = root); used to DRAW the heap.

        Time:  O(n)
        Space: O(n)
        """
        return list(self._a)

    def drain(self):
        """Pop everything: the items come out best-first (this is heap sort).

        Time:  O(n log n)
        Space: O(n)
        """
        out = []
        while self._a:
            out.append(self.pop())
        return out

    def _sift_up(self, i):
        """Swap item i with its parent while it is bigger than the parent.

        Time:  O(log n)
        Space: O(1)
        """
        a, key = self._a, self._key
        while i > 0:
            parent = (i - 1) // 2
            if key(a[i]) > key(a[parent]):
                a[i], a[parent] = a[parent], a[i]
                i = parent
            else:
                break

    def _sift_down(self, i):
        """Swap item i with its bigger child while a child is bigger than it.

        Time:  O(log n)
        Space: O(1)
        """
        a, key, n = self._a, self._key, len(self._a)
        while True:
            big, left, right = i, 2 * i + 1, 2 * i + 2
            if left < n and key(a[left]) > key(a[big]):
                big = left
            if right < n and key(a[right]) > key(a[big]):
                big = right
            if big == i:
                return
            a[i], a[big] = a[big], a[i]
            i = big


# ==========================================================================
# 4. CIRCULAR QUEUE  (array based ring buffer, FIFO, fixed capacity)
# ==========================================================================
class CircularQueue:
    """FIFO queue stored in a fixed-size array that wraps around (a "ring buffer").

    Used as the bot's SLIDING WINDOW of recent observations: when it is full the oldest
    entry is dequeued to make room, so the bot only remembers the last few events.
    Why not a plain list with pop(0)?  Removing the front of a Python list shifts every
    other item (O(n)).  Here `head` simply moves forward and wraps with `% capacity`,
    so both enqueue and dequeue are O(1) and no memory is ever re-allocated.
    """

    def __init__(self, capacity):
        """Create an empty queue that can hold `capacity` items.

        Time:  O(capacity)  (allocating the array)
        Space: O(capacity)
        """
        if capacity < 1:
            raise ValueError("capacity must be at least 1")
        self._buf = [None] * capacity
        self._cap = capacity
        self._head = 0           # index of the oldest item
        self._size = 0

    def __len__(self):
        """Number of items currently stored.

        Time:  O(1)
        Space: O(1)
        """
        return self._size

    def is_empty(self):
        """True when nothing is stored.

        Time:  O(1)
        Space: O(1)
        """
        return self._size == 0

    def is_full(self):
        """True when every slot is used (the next enqueue would fail).

        Time:  O(1)
        Space: O(1)
        """
        return self._size == self._cap

    def enqueue(self, item):
        """Add `item` at the back; IndexError if the queue is full.

        The back slot is (head + size) % capacity -- the modulo is what makes the array "circular".

        Time:  O(1)
        Space: O(1)
        """
        if self.is_full():
            raise IndexError("enqueue into a full queue")
        self._buf[(self._head + self._size) % self._cap] = item
        self._size += 1

    def dequeue(self):
        """Remove and return the OLDEST item; IndexError if empty.

        Time:  O(1)
        Space: O(1)
        """
        if self.is_empty():
            raise IndexError("dequeue from empty queue")
        item = self._buf[self._head]
        self._buf[self._head] = None
        self._head = (self._head + 1) % self._cap
        self._size -= 1
        return item

    def peek(self):
        """Return the oldest item without removing it; IndexError if empty.

        Time:  O(1)
        Space: O(1)
        """
        if self.is_empty():
            raise IndexError("peek at empty queue")
        return self._buf[self._head]

    def clear(self):
        """Forget everything.

        Time:  O(capacity)
        Space: O(1)
        """
        self._buf = [None] * self._cap
        self._head = 0
        self._size = 0

    def to_list(self):
        """Oldest-to-newest copy of the stored items (used to DRAW the memory).

        Time:  O(n)
        Space: O(n)
        """
        return [self._buf[(self._head + i) % self._cap] for i in range(self._size)]